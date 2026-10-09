import { useState } from 'react'
import { Alert, Box, Button, CircularProgress, Table, TableBody, TableCell, TableHead, TableRow, Typography } from '@mui/material'
import { DescriptionOutlined, GetAppRounded, UploadFileRounded } from '@mui/icons-material'
import { FormDialog } from './Common'
import { downloadTemplate, parseImportFile, type ImportRow } from '../lib/export'

// Standard import flow for list pages: xlsx/csv file, row preview, row-level errors near the source.
export function ImportDialog({ open, onClose, title, subtitle, headers, sample, templateName, onRows }: {
  open: boolean
  onClose: () => void
  title: string
  subtitle?: string
  headers: string[]
  sample?: ImportRow
  templateName: string
  onRows: (rows: ImportRow[]) => Promise<string[]>
}) {
  const [fileName, setFileName] = useState('')
  const [rows, setRows] = useState<ImportRow[]>([])
  const [errors, setErrors] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [parsing, setParsing] = useState(false)

  const reset = () => { setFileName(''); setRows([]); setErrors([]); setBusy(false); setParsing(false) }
  const close = () => { if (!busy) { reset(); onClose() } }
  const pick = async (file: File | undefined) => {
    if (!file) return
    setParsing(true); setErrors([]); setFileName(file.name)
    try {
      const parsed = await parseImportFile(file)
      const missing = headers.filter(h => !parsed.headers.includes(h))
      if (missing.length) {
        setRows([])
        setErrors([`Missing required columns: ${missing.join(', ')}. Download the template for the expected format.`])
      } else {
        setRows(parsed.rows)
        if (!parsed.rows.length) setErrors(['The file contains no data rows.'])
      }
    } catch {
      setRows([])
      setErrors(['Could not read this file. Use .xlsx or .csv.'])
    } finally { setParsing(false) }
  }
  const run = async () => {
    setBusy(true); setErrors([])
    try {
      const problems = await onRows(rows)
      if (problems.length) setErrors(problems)
      else { reset(); onClose() }
    } catch (e) {
      setErrors([(e as Error).message])
    } finally { setBusy(false) }
  }

  return <FormDialog open={open} onClose={close} onSubmit={run} busy={busy} title={title} subtitle={subtitle} submitLabel={`Import ${rows.length || ''} ${rows.length === 1 ? 'row' : 'rows'}`.trim()}>
    <Box display="grid" gap={2} pt={.5}>
      <Box display="flex" gap={1} flexWrap="wrap">
        <Button component="label" variant="outlined" startIcon={parsing ? <CircularProgress size={15}/> : <UploadFileRounded sx={{ fontSize: 18 }}/>} disabled={busy || parsing}>
          Choose file (.xlsx or .csv)
          <input hidden type="file" accept=".xlsx,.xls,.csv" onChange={e => { pick(e.target.files?.[0]); e.target.value = '' }}/>
        </Button>
        <Button color="inherit" startIcon={<GetAppRounded sx={{ fontSize: 18 }}/>} onClick={() => downloadTemplate(templateName, headers, sample)} disabled={busy}>Download template</Button>
      </Box>
      {fileName && <Box display="flex" alignItems="center" gap={1}><DescriptionOutlined sx={{ fontSize: 17, color: 'text.secondary' }}/><Typography fontSize={12.5} fontWeight={700}>{fileName}</Typography><Typography fontSize={12} color="text.secondary">· {rows.length} rows detected</Typography></Box>}
      {rows.length > 0 && <Box sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 2, maxHeight: 260, overflow: 'auto' }}>
        <Table size="small" stickyHeader>
          <TableHead><TableRow>{headers.map(h => <TableCell key={h} sx={{ fontWeight: 800, fontSize: 11, bgcolor: 'background.paper' }}>{h}</TableCell>)}</TableRow></TableHead>
          <TableBody>{rows.slice(0, 50).map((row, i) => <TableRow key={i}>{headers.map(h => <TableCell key={h} sx={{ fontSize: 12, maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{row[h] || '—'}</TableCell>)}</TableRow>)}</TableBody>
        </Table>
        {rows.length > 50 && <Typography fontSize={11} color="text.secondary" sx={{ p: 1.2 }}>Preview shows the first 50 of {rows.length} rows.</Typography>}
      </Box>}
      {errors.map((message, i) => <Alert key={i} severity="error" sx={{ fontSize: 12.5 }}>{message}</Alert>)}
    </Box>
  </FormDialog>
}
