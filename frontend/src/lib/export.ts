import type { ColDef } from 'ag-grid-community'

// Standard export/import toolkit for list pages: CSV + XLSX + PDF out, XLSX + CSV in.
// xlsx and jspdf are loaded on demand so list pages stay light.

export type ExportColumn<T> = { header: string; value: (row: T) => string }

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
  return /[",\n]/.test(cell) ? `"${cell.replace(/"/g, '""')}"` : cell
}

export function exportCsv<T>(filename: string, rows: T[], columns: ExportColumn<T>[]) {
  const csv = matrix(rows, columns).map(line => line.map(csvCell).join(',')).join('\r\n')
  download(filename, 'text/csv;charset=utf-8', '\uFEFF' + csv)
}

export async function exportXlsx<T>(filename: string, rows: T[], columns: ExportColumn<T>[]) {
  const XLSX = await import('xlsx')
  const sheet = XLSX.utils.aoa_to_sheet(matrix(rows, columns))
  const book = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(book, sheet, 'Data')
  XLSX.writeFile(book, filename)
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

export type ImportRow = Record<string, string>

// Parses .xlsx and .csv files into header-keyed rows for the import preview.
export async function parseImportFile(file: File): Promise<{ headers: string[]; rows: ImportRow[] }> {
  const XLSX = await import('xlsx')
  const data = await file.arrayBuffer()
  const book = XLSX.read(data, { type: 'array' })
  const sheet = book.Sheets[book.SheetNames[0]]
  const raw = XLSX.utils.sheet_to_json(sheet, { header: 1, defval: '', blankrows: false, raw: false }) as unknown as string[][]
  if (!raw.length) return { headers: [], rows: [] }
  const headers = raw[0].map(h => String(h).trim())
  const rows = raw.slice(1)
    .filter(line => line.some(cell => String(cell).trim() !== ''))
    .map(line => Object.fromEntries(headers.map((h, i) => [h, String(line[i] ?? '').trim()])))
  return { headers, rows }
}

export function downloadTemplate(filename: string, headers: string[], sample: ImportRow = {}) {
  const line = headers.map(h => csvCell(sample[h] ?? '')).join(',')
  download(filename, 'text/csv;charset=utf-8', '\uFEFF' + headers.join(',') + '\r\n' + line + '\r\n')
}
