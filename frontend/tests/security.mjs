// Run with npm run test:security. Exercise the actual TypeScript module without a test framework.
import assert from 'node:assert/strict'
import { readFile, writeFile, mkdir, unlink } from 'node:fs/promises'
import ts from 'typescript'

const generated = new URL('../node_modules/.cache/security-export.mjs', import.meta.url)
await mkdir(new URL('.', generated), { recursive: true })
const source = await readFile(new URL('../src/lib/export.ts', import.meta.url), 'utf8')
await writeFile(generated, ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
}).outputText)
try {
  const toolkit = await import(generated.href)
  for (const value of ['=SUM(A1)', '+cmd', '-cmd', '@SUM(A1)', '  =cmd', '\t=cmd', '\rtext', '\ntext']) {
    assert.equal(toolkit.spreadsheetText(value), "'" + value)
  }
  assert.equal(toolkit.spreadsheetText('ordinary text'), 'ordinary text')
  let output
  const original = URL.createObjectURL
  URL.createObjectURL = blob => { output = blob; return 'blob:test' }
  globalThis.document = { createElement: () => ({ click() {} }) }
  toolkit.exportCsv('test.csv', [{ text: ' =HYPERLINK("evil")' }], [{ header: '+header', value: r => r.text }])
  assert.equal(await output.text(), "'+header\r\n\"' =HYPERLINK(\"\"evil\"\")\"")
  URL.createObjectURL = original
  const csv = { name: 'test.csv', size: 100, text: async () => 'Name,Notes\r\n"A,B","Line 1\nLine 2"' }
  const parsed = await toolkit.parseImportFile(csv)
  assert.deepEqual(parsed.headers, ['Name', 'Notes'])
  assert.deepEqual(parsed.rows, [{ Name: 'A,B', Notes: 'Line 1\nLine 2' }])
  await assert.rejects(toolkit.parseImportFile({ name: 'large.xlsx', size: 11 * 1024 * 1024 }), /10 MiB/)
  await assert.rejects(toolkit.parseImportFile({ name: 'old.xls', size: 12 }), /xlsx or .csv/)
  await assert.rejects(toolkit.parseImportFile({ name: 'many.csv', size: 100, text: async () => 'Header\n' + 'row\n'.repeat(10001) }), /10,000 rows/)

  // Verify formulas are literal text in the replacement writer and XML/HTML characters round-trip.
  const { default: writeXlsxFile } = await import('write-excel-file/node')
  const { readSheet } = await import('read-excel-file/node')
  const values = ['=1+1', '@SUM(A1)', '<script>alert(1)</script>', 'A & B', '123']
  const buffer = await writeXlsxFile([values.map(value => ({ type: String, value }))]).toBuffer()
  assert.deepEqual(await readSheet(buffer), [values])
  const { unzipSync, strFromU8 } = await import('fflate')
  const workbookFiles = unzipSync(buffer)
  assert.doesNotMatch(strFromU8(workbookFiles['xl/worksheets/sheet1.xml']), /<f[ >]/)
  toolkit.validateWorkbookZip(buffer.buffer.slice(buffer.byteOffset, buffer.byteOffset + buffer.byteLength))
  assert.throws(() => toolkit.validateWorkbookZip(new ArrayBuffer(20)), /directory is invalid/)
  const bomb = new Uint8Array(46 + 22)
  const view = new DataView(bomb.buffer)
  view.setUint32(0, 0x02014b50, true)
  view.setUint32(24, 60 * 1024 * 1024, true)
  view.setUint32(46, 0x06054b50, true)
  view.setUint16(46 + 8, 1, true); view.setUint16(46 + 10, 1, true)
  view.setUint32(46 + 12, 46, true)
  assert.throws(() => toolkit.validateWorkbookZip(bomb.buffer), /safe processing limits/)
  console.log('Security export/import checks passed (formulas, CSV quoting, limits, XLSX text round trip).')
} finally {
  await unlink(generated)
}
