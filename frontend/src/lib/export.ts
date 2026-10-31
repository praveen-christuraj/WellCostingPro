import type { ColDef } from 'ag-grid-community'

// Standard export/import toolkit for list pages: CSV + XLSX + PDF out, XLSX + CSV in.
// The spreadsheet libraries are loaded on demand so list pages stay light.
//
// Every cell leaves the browser as *data*. Text that a spreadsheet could read as a
// formula (`=`, `+`, `-`, `@`, or any of those after whitespace/control characters)
// is prefixed with an apostrophe, so opening an export cannot execute a formula
// stored by another user. XLSX cells are explicitly typed as strings for the same
// reason; the writer never emits a `<f>` formula element for our data.

export type ExportColumn<T> = { header: string; value: (row: T) => string }

export const MAX_IMPORT_BYTES = 10 * 1024 * 1024
export const MAX_IMPORT_ROWS = 10_000
export const MAX_IMPORT_COLUMNS = 200
export const MAX_ARCHIVE_ENTRIES = 2_000
export const MAX_EXPANDED_BYTES = 50 * 1024 * 1024

const FORMULA_LEAD = /^[\s\u0000-\u001f]*[=+@-]/
const CONTROL_LEAD = /^[\t\r\n]/

/** Neutralise a spreadsheet cell without changing ordinary text or numbers. */
export function spreadsheetText(value: string): string {
  if (typeof value !== 'string') return value as unknown as string
  return FORMULA_LEAD.test(value) || CONTROL_LEAD.test(value) ? `'${value}` : value
}

export function exportColumns<T extends object>(columns: ColDef<T>[]): ExportColumn<T>[] {
  return columns
    .filter(c => c.headerName && c.headerName.toUpperCase() !== 'ACTIONS' && (c.field || c.valueGetter || c.valueFormatter))
    .map(c => ({
      header: c.headerName as string,
      value: (row: T) => {
        const params = { data: row, value: c.field ? (row as Record<string, unknown>)[c.field] : undefined } as never
        if (typeof c.valueGetter === 'function') return String(c.valueGetter(params) ?? '')
        if (typeof c.valueFormatter === 'function') return String(c.valueFormatter(params) ?? '')
        return String((row as Record<string, unknown>)[c.field as string] ?? '')
      },
    }))
}

function matrix<T>(rows: T[], columns: ExportColumn<T>[]): string[][] {
  return [columns.map(c => c.header), ...rows.map(r => columns.map(c => c.value(r)))]
}

function download(filename: string, mime: string, content: BlobPart) {
  const url = URL.createObjectURL(new Blob([content], { type: mime }))
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}

function csvCell(cell: string) {
  const safe = spreadsheetText(cell)
  return /[",\n\r]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe
}

export function exportCsv<T>(filename: string, rows: T[], columns: ExportColumn<T>[]) {
  const csv = matrix(rows, columns).map(line => line.map(csvCell).join(',')).join('\r\n')
  download(filename, 'text/csv;charset=utf-8', '\uFEFF' + csv)
}

export async function exportXlsx<T>(filename: string, rows: T[], columns: ExportColumn<T>[]) {
  const { default: writeXlsxFile } = await import('write-excel-file/browser')
  // `type: String` makes the writer emit inline/shared *text*, never a formula.
  const data = matrix(rows, columns).map(line =>
    line.map(value => ({ type: String, value: spreadsheetText(String(value)) })),
  )
  await writeXlsxFile(data, { sheet: 'Data' }).toFile(filename)
}

export async function exportPdf<T>(filename: string, title: string, rows: T[], columns: ExportColumn<T>[]) {
  const [{ jsPDF }, autoTableModule] = await Promise.all([import('jspdf'), import('jspdf-autotable')])
  const autoTable = autoTableModule.default
  const doc = new jsPDF({ orientation: columns.length > 6 ? 'landscape' : 'portrait' })
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(13)
  doc.text(title, 14, 16)
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(9)
  doc.text(`Generated ${new Date().toLocaleString()} · ${rows.length} records`, 14, 22)
  autoTable(doc, {
    startY: 27,
    head: [columns.map(c => c.header)],
    body: rows.map(r => columns.map(c => c.value(r))),
    styles: { fontSize: 8, cellPadding: 2.5 },
    headStyles: { fillColor: [18, 58, 99], textColor: 255 },
  })
  doc.save(filename)
}

/**
 * Preflight an XLSX (a ZIP container) before a decoder touches it.
 *
 * A workbook is a ZIP archive, and a hostile one can claim tiny compressed sizes
 * while expanding to gigabytes (or contain thousands of entries) to exhaust the
 * browser tab. The central directory is read directly: ZIP64 and encrypted
 * archives are refused, the entry count is capped and the declared expanded size
 * is budgeted. The decoder still runs with the row/column limits below.
 */
export function validateWorkbookZip(buffer: ArrayBuffer): void {
  const bytes = new Uint8Array(buffer)
  const view = new DataView(buffer)
  if (bytes.length < 22) throw new Error('The workbook directory is invalid or truncated.')
  let end = -1
  const floor = Math.max(0, bytes.length - 22 - 0xffff)
  for (let index = bytes.length - 22; index >= floor; index -= 1) {
    if (view.getUint32(index, true) === 0x06054b50) { end = index; break }
  }
  if (end < 0) throw new Error('The workbook directory is invalid or truncated.')
  const entries = view.getUint16(end + 10, true)
  const directorySize = view.getUint32(end + 12, true)
  const directoryOffset = view.getUint32(end + 16, true)
  if (entries === 0xffff || directorySize === 0xffffffff || directoryOffset === 0xffffffff) {
    throw new Error('ZIP64 workbooks exceed the safe processing limits for import.')
  }
  if (entries > MAX_ARCHIVE_ENTRIES) throw new Error('The workbook has too many entries for the safe processing limits.')
  if (directoryOffset + directorySize > bytes.length) throw new Error('The workbook directory is invalid or truncated.')
  let cursor = directoryOffset
  let expanded = 0
  for (let entry = 0; entry < entries; entry += 1) {
    if (cursor + 46 > bytes.length || view.getUint32(cursor, true) !== 0x02014b50) {
      throw new Error('The workbook directory is invalid or truncated.')
    }
    const flags = view.getUint16(cursor + 8, true)
    const compressed = view.getUint32(cursor + 20, true)
    const uncompressed = view.getUint32(cursor + 24, true)
    const nameLength = view.getUint16(cursor + 28, true)
    const extraLength = view.getUint16(cursor + 30, true)
    const commentLength = view.getUint16(cursor + 32, true)
    if (compressed === 0xffffffff || uncompressed === 0xffffffff) {
      throw new Error('ZIP64 workbooks exceed the safe processing limits for import.')
    }
    if (flags & 0x1) throw new Error('Encrypted workbooks are not supported.')
    expanded += uncompressed
    if (expanded > MAX_EXPANDED_BYTES) {
      throw new Error('The workbook expands beyond the safe processing limits for import.')
    }
    cursor += 46 + nameLength + extraLength + commentLength
  }
}

type ImportFile = File & { text?: () => Promise<string> }

export type ImportRow = Record<string, string>

function shape(rows: string[][]): { headers: string[]; rows: ImportRow[] } {
  if (!rows.length) return { headers: [], rows: [] }
  const headers = (rows[0] ?? []).map(cell => String(cell ?? '').trim())
  if (headers.length > MAX_IMPORT_COLUMNS) {
    throw new Error(`This file has ${headers.length} columns; at most ${MAX_IMPORT_COLUMNS} are supported.`)
  }
  const body = rows.slice(1).filter(line => line.some(cell => String(cell ?? '').trim() !== ''))
  if (body.length > MAX_IMPORT_ROWS) {
    throw new Error(`This file has ${body.length.toLocaleString()} rows; at most 10,000 rows can be imported at once.`)
  }
  return {
    headers,
    rows: body.map(line => Object.fromEntries(headers.map((header, index) => [header, String(line[index] ?? '').trim()]))),
  }
}

/** Parse a .csv or .xlsx file into header-keyed rows for the import preview. */
export async function parseImportFile(file: ImportFile): Promise<{ headers: string[]; rows: ImportRow[] }> {
  const name = (file.name || '').toLowerCase()
  if (!name.endsWith('.xlsx') && !name.endsWith('.csv')) {
    throw new Error('Use an .xlsx or .csv file. Legacy .xls workbooks are not accepted.')
  }
  if (file.size > MAX_IMPORT_BYTES) throw new Error('Choose a file smaller than 10 MiB.')
  if (name.endsWith('.csv')) {
    const text = (await file.text()).replace(/^\uFEFF/, '')
    const { default: Papa } = await import('papaparse')
    const parsed = Papa.parse<string[]>(text, { skipEmptyLines: 'greedy' })
    return shape((parsed.data as unknown as string[][]).map(line => (Array.isArray(line) ? line : [line])))
  }
  const buffer = await file.arrayBuffer()
  validateWorkbookZip(buffer)
  const { default: readXlsxFile } = await import('read-excel-file/browser')
  const data = await readXlsxFile(buffer)
  return shape((data as unknown as string[][]).map(line => line.map(cell => String(cell ?? ''))))
}

export function downloadTemplate(filename: string, headers: string[], sample: ImportRow | ImportRow[] = {}) {
  // More than one sample row is used where a file can hold several record kinds.
  const rows = (Array.isArray(sample) ? sample : [sample])
    .map(row => headers.map(h => csvCell(row[h] ?? '')).join(','))
    .join('\r\n')
  download(filename, 'text/csv;charset=utf-8', '\uFEFF' + headers.map(csvCell).join(',') + '\r\n' + rows + '\r\n')
}
