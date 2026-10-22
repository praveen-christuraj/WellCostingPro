import { useEffect, useMemo, useRef, useState } from 'react'
import {
  AddRounded, ContentCopyRounded, DeleteOutlineRounded, DownloadRounded, KeyboardOutlined,
  PlaylistAddRounded, RestartAltRounded, SaveOutlined, UploadFileRounded,
} from '@mui/icons-material'
import { Alert, Box, Button, IconButton, Tooltip, Typography } from '@mui/material'
import { dailyMoney } from '../../lib/dailyCost'
import {
  applySuggestion, blankDraftRow, duplicateDraftRow, lihLineTotal, rowIsBlank, rowState,
  validateDraft, type LihCostItemSuggestion, type LihCostUomOption, type LihCostLineInput,
  type LihDraftRow, type LihField, type LihRowErrors,
} from '../../lib/lihCost'

/**
 * Worksheet-style entry for the LIH register.
 *
 * A whole day is edited here and saved once: rows can be added, duplicated,
 * pasted from Excel, reordered by adding at a position, and edited in place —
 * including rows that were already saved. Keyboard entry is the primary path
 * (Enter/Tab/Alt+arrows move between cells, Ctrl+D duplicates, Ctrl+S saves),
 * and a block copied from a spreadsheet pastes straight into the grid.
 */

type Column = { field: LihField; label: string; width: number; numeric?: boolean; align?: 'right' }

const COLUMNS: Column[] = [
  { field: 'item_description', label: 'Item description', width: 264 },
  { field: 'od_size', label: 'OD', width: 86, numeric: true, align: 'right' },
  { field: 'id_size', label: 'ID', width: 86, numeric: true, align: 'right' },
  { field: 'fish_neck_od', label: 'Fish neck OD', width: 112, numeric: true, align: 'right' },
  { field: 'fish_neck_length', label: 'Fish neck length', width: 132, numeric: true, align: 'right' },
  { field: 'connection', label: 'Connection', width: 126 },
  { field: 'length', label: 'Length', width: 96, numeric: true, align: 'right' },
  { field: 'serial_number', label: 'Serial number', width: 140 },
  { field: 'no_of_units', label: 'Units', width: 92, numeric: true, align: 'right' },
  { field: 'unit', label: 'UOM', width: 98 },
  { field: 'unit_cost', label: 'Unit cost', width: 122, numeric: true, align: 'right' },
  { field: 'remarks', label: 'Remarks', width: 210 },
]

const SHORTCUTS: [string, string][] = [
  ['Ctrl / ⌘ + S', 'Save every item on the sheet'],
  ['Ctrl / ⌘ + Enter', 'Add a new item at the end'],
  ['Ctrl / ⌘ + D', 'Duplicate the current row as a new item'],
  ['Ctrl / ⌘ + I', 'Insert an item below the current row'],
  ['Enter / Shift + Enter', 'Move down / up a column'],
  ['Tab / Shift + Tab', 'Move to the next / previous field'],
  ['Alt + Arrow keys', 'Move freely around the sheet'],
  ['Ctrl / ⌘ + V', 'Paste a block copied from Excel'],
]

export type LihWorksheetProps = {
  rows: LihDraftRow[]
  onRowsChange: (rows: LihDraftRow[]) => void
  currency: string
  uoms: LihCostUomOption[]
  suggestions: LihCostItemSuggestion[]
  /** Saved items on the day that are no longer on the sheet (removed on save). */
  removedCount: number
  canEdit: boolean
  canImport: boolean
  canExport: boolean
  saving: boolean
  dirty: boolean
  saveError: string
  onSave: () => void
  onDiscard: () => void
  onImport?: () => void
  /** Opens the page's CSV/XLSX/PDF export menu for the current sheet. */
  onExportSheet?: (anchor: HTMLElement) => void
  /** Items already stored on the day; drives the "already saved" wording. */
  savedCount: number
  /** Focus the first cell when the sheet opens after the day selection changes. */
  autoFocus?: boolean
}

type FocusRequest = { key: string; column: number }

export function LihWorksheet({
  rows, onRowsChange, currency, uoms, suggestions, removedCount, canEdit, canImport, canExport, saving, dirty,
  saveError, onSave, onDiscard, onImport, onExportSheet, savedCount, autoFocus = false,
}: LihWorksheetProps) {
  const rootRef = useRef<HTMLDivElement | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [focusRequest, setFocusRequest] = useState<FocusRequest | null>(null)
  const [showShortcuts, setShowShortcuts] = useState(false)
  const [attemptedSave, setAttemptedSave] = useState(false)
  const [currentRow, setCurrentRow] = useState(0)

  const problems = useMemo(() => validateDraft(rows), [rows])
  const problemsByKey = useMemo(
    () => new Map(problems.map(problem => [problem.key, problem.errors] as const)),
    [problems],
  )
  const showErrors = attemptedSave || Boolean(saveError)

  const namedRows = rows.filter(row => !rowIsBlank(row.values))
  const sheetTotal = namedRows.reduce((sum, row) => sum + lihLineTotal(row.values), 0)
  const changedCount = rows.filter(row => rowState(row) !== 'saved' && !rowIsBlank(row.values)).length

  useEffect(() => {
    // A row removed from the sheet must not stay selected.
    const live = new Set(rows.map(row => row.key))
    setSelected(current => {
      const next = new Set([...current].filter(key => live.has(key)))
      return next.size === current.size ? current : next
    })
  }, [rows])

  useEffect(() => {
    if (!focusRequest) return
    const node = rootRef.current?.querySelector<HTMLElement>(
      `[data-row-key="${focusRequest.key}"][data-col-index="${focusRequest.column}"]`,
    )
    node?.focus()
    setFocusRequest(null)
  }, [focusRequest, rows])

  const autoFocusApplied = useRef(false)
  useEffect(() => {
    if (!autoFocus) { autoFocusApplied.current = false; return }
    if (autoFocusApplied.current) return
    const first = rows[0]
    if (!first) return
    autoFocusApplied.current = true
    setFocusRequest({ key: first.key, column: 0 })
  }, [autoFocus, rows])

  const unitOptions = useMemo(() => {
    const codes = new Set(uoms.map(uom => uom.code))
    const labels = new Map(uoms.map(uom => [uom.code, uom.display_name] as const))
    for (const row of rows) {
      const value = row.values.unit.trim()
      if (value && !codes.has(value)) {
        codes.add(value)
        labels.set(value, `${value} (not in Master Data)`)
      }
    }
    return [...codes].map(code => ({ code, label: labels.get(code) ?? code }))
  }, [uoms, rows])

  const focusCell = (rowKey: string, column: number) => setFocusRequest({ key: rowKey, column })

  const updateRow = (key: string, values: LihCostLineInput) => {
    onRowsChange(rows.map(row => (row.key === key ? { ...row, values } : row)))
  }

  const addRow = (at?: number) => {
    const row = blankDraftRow()
    const index = at === undefined ? rows.length : Math.max(0, Math.min(at, rows.length))
    const next = [...rows.slice(0, index), row, ...rows.slice(index)]
    onRowsChange(next)
    focusCell(row.key, 0)
    setCurrentRow(index)
  }

  const duplicateRow = (index: number) => {
    const source = rows[index]
    if (!source || !canEdit) return
    const row = duplicateDraftRow(source)
    const next = [...rows.slice(0, index + 1), row, ...rows.slice(index + 1)]
    onRowsChange(next)
    focusCell(row.key, 0)
    setCurrentRow(index + 1)
  }

  const removeRows = (keys: string[]) => {
    if (!keys.length || !canEdit) return
    const remove = new Set(keys)
    const next = rows.filter(row => !remove.has(row.key))
    onRowsChange(next.length ? next : [blankDraftRow()])
    setSelected(new Set())
  }

  const selectRow = (key: string, checked: boolean) => {
    setSelected(current => {
      const next = new Set(current)
      if (checked) next.add(key)
      else next.delete(key)
      return next
    })
  }

  const allSelected = rows.length > 0 && rows.every(row => selected.has(row.key))

  const findSuggestion = (description: string) => {
    const target = description.trim().toLowerCase()
    if (!target) return undefined
    return suggestions.find(item => item.item_description.trim().toLowerCase() === target)
  }

  const commitDescription = (row: LihDraftRow) => {
    if (!row.values.item_description.trim()) return
    const suggestion = findSuggestion(row.values.item_description)
    if (!suggestion) return
    const values = applySuggestion(row.values, suggestion)
    const unchanged = (Object.keys(values) as LihField[]).every(field => values[field] === row.values[field])
    if (!unchanged) updateRow(row.key, values)
  }

  const handleKeyDown = (
    event: React.KeyboardEvent<HTMLElement>, rowIndex: number, columnIndex: number,
  ) => {
    const mod = event.ctrlKey || event.metaKey
    const key = event.key
    if (mod && key === 'Enter') {
      event.preventDefault()
      addRow()
      return
    }
    if (mod && key.toLowerCase() === 'd') {
      event.preventDefault()
      duplicateRow(rowIndex)
      return
    }
    if (mod && key.toLowerCase() === 'i') {
      event.preventDefault()
      addRow(rowIndex + 1)
      return
    }
    if (key === 'Enter') {
      event.preventDefault()
      if (event.shiftKey) {
        if (rowIndex > 0) focusCell(rows[rowIndex - 1].key, columnIndex)
      } else if (rowIndex >= rows.length - 1) {
        addRow()
      } else {
        focusCell(rows[rowIndex + 1].key, columnIndex)
      }
      return
    }
    if (key === 'Tab') {
      if (event.shiftKey) {
        if (columnIndex === 0) {
          if (rowIndex > 0) {
            event.preventDefault()
            focusCell(rows[rowIndex - 1].key, COLUMNS.length - 1)
          }
          return
        }
        event.preventDefault()
        focusCell(rows[rowIndex].key, columnIndex - 1)
        return
      }
      if (columnIndex < COLUMNS.length - 1) {
        event.preventDefault()
        focusCell(rows[rowIndex].key, columnIndex + 1)
      } else if (rowIndex < rows.length - 1) {
        event.preventDefault()
        focusCell(rows[rowIndex + 1].key, 0)
      }
      return
    }
    if (event.altKey && key.startsWith('Arrow')) {
      const moves: Record<string, [number, number]> = {
        ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1],
      }
      const [rowDelta, columnDelta] = moves[key] ?? [0, 0]
      const targetRow = rowIndex + rowDelta
      const targetColumn = columnIndex + columnDelta
      if (targetRow < 0 || targetRow >= rows.length || targetColumn < 0 || targetColumn >= COLUMNS.length) return
      event.preventDefault()
      focusCell(rows[targetRow].key, targetColumn)
    }
  }

  const handlePaste = (event: React.ClipboardEvent<HTMLElement>, rowIndex: number, columnIndex: number) => {
    if (!canEdit) return
    const text = event.clipboardData?.getData('text/plain') ?? ''
    if (!text) return
    const lines = text.replace(/\r/g, '').split('\n')
    if (lines.length <= 1 && !lines[0].includes('\t')) return
    event.preventDefault()
    const matrix = lines
      .filter((line, index) => !(index === lines.length - 1 && line.trim() === ''))
      .map(line => line.split('\t'))
    if (!matrix.length) return
    const next = [...rows]
    while (next.length < rowIndex + matrix.length) next.push(blankDraftRow())
    matrix.forEach((cells, rowOffset) => {
      const target = next[rowIndex + rowOffset]
      if (!target) return
      const values = { ...target.values }
      cells.forEach((cell, columnOffset) => {
        const column = COLUMNS[columnIndex + columnOffset]
        if (column) values[column.field] = cell.trim()
      })
      next[rowIndex + rowOffset] = { ...target, values }
    })
    onRowsChange(next)
    const lastIndex = rowIndex + matrix.length - 1
    if (next[lastIndex]) focusCell(next[lastIndex].key, Math.min(columnIndex + matrix[0].length, COLUMNS.length - 1))
  }

  const fieldValue = (row: LihDraftRow, column: Column) => row.values[column.field]

  const rowClass = (row: LihDraftRow) => {
    const state = rowState(row)
    return `lih-row lih-row--${state}${selected.has(row.key) ? ' is-selected' : ''}`
  }

  return <Box className="lih-worksheet">
    <Box className="lih-worksheet__bar">
      <Box minWidth={0}>
        <Typography fontWeight={800} fontSize={14.5}>LIH worksheet</Typography>
        <Typography color="text.secondary" fontSize={11.5} mt={0.25}>
          {canEdit
            ? 'Type each item, duplicate a similar one, or paste a block from Excel. Every row on this sheet is saved together with one save.'
            : 'This worksheet is read-only with your current permissions.'}
        </Typography>
      </Box>
      <Box display="flex" gap={1} flexWrap="wrap" alignItems="center">
        <Tooltip title="Keyboard shortcuts">
          <Button
            size="small"
            color="inherit"
            aria-expanded={showShortcuts}
            startIcon={<KeyboardOutlined sx={{ fontSize: 17 }}/>}
            onClick={() => setShowShortcuts(value => !value)}
          >
            Shortcuts
          </Button>
        </Tooltip>
        {canExport && onExportSheet && <Button
          size="small"
          variant="outlined"
          color="inherit"
          startIcon={<DownloadRounded sx={{ fontSize: 18 }}/>}
          aria-haspopup="menu"
          onClick={event => onExportSheet(event.currentTarget)}
        >
          Export sheet
        </Button>}
        {canImport && onImport && <Button size="small" variant="outlined" startIcon={<UploadFileRounded sx={{ fontSize: 18 }}/>} onClick={onImport}>
          Import items
        </Button>}
        {canEdit && <Button
          size="small"
          variant="outlined"
          color="inherit"
          startIcon={<RestartAltRounded sx={{ fontSize: 18 }}/>}
          disabled={!dirty || saving}
          onClick={onDiscard}
        >
          Discard changes
        </Button>}
        {canEdit && <Button
          size="small"
          variant="contained"
          startIcon={<SaveOutlined sx={{ fontSize: 18 }}/>}
          disabled={!dirty || saving}
          onClick={() => { setAttemptedSave(true); onSave() }}
        >
          {saving ? 'Saving…' : 'Save all items'}
        </Button>}
      </Box>
    </Box>

    {showShortcuts && <Box className="lih-shortcuts" role="region" aria-label="Worksheet keyboard shortcuts">
      {SHORTCUTS.map(([keys, action]) => <Box key={keys} className="lih-shortcut">
        <span className="lih-shortcut__keys">{keys}</span>
        <span>{action}</span>
      </Box>)}
    </Box>}

    {canEdit && <Box className="lih-worksheet__tools">
      <Button size="small" startIcon={<AddRounded sx={{ fontSize: 17 }}/>} onClick={() => addRow()} disabled={saving}>
        Add row
      </Button>
      <Button
        size="small"
        startIcon={<ContentCopyRounded sx={{ fontSize: 16 }}/>}
        onClick={() => duplicateRow(Math.min(currentRow, rows.length - 1))}
        disabled={saving || !rows.length}
      >
        Duplicate row
      </Button>
      <Button
        size="small"
        startIcon={<PlaylistAddRounded sx={{ fontSize: 17 }}/>}
        onClick={() => addRow(Math.min(currentRow + 1, rows.length))}
        disabled={saving || !rows.length}
      >
        Insert below
      </Button>
      <Button
        size="small"
        color="error"
        startIcon={<DeleteOutlineRounded sx={{ fontSize: 17 }}/>}
        onClick={() => removeRows([...selected])}
        disabled={saving || !selected.size}
      >
        Remove selected{selected.size ? ` (${selected.size})` : ''}
      </Button>
      <Box ml="auto" display="flex" alignItems="center" gap={1.5} flexWrap="wrap">
        {changedCount > 0 && <Typography fontSize={11.5} fontWeight={700} color="warning.main">
          {changedCount} unsaved item{changedCount === 1 ? '' : 's'}
        </Typography>}
        {removedCount > 0 && <Typography fontSize={11.5} fontWeight={700} color="error.main">
          {removedCount} saved item{removedCount === 1 ? '' : 's'} will be removed on save
        </Typography>}
        <Typography fontSize={11.5} color="text.secondary">
          {namedRows.length} item{namedRows.length === 1 ? '' : 's'} · {dailyMoney(sheetTotal, currency)}
        </Typography>
      </Box>
    </Box>}

    <datalist id="lih-item-suggestions">
      {suggestions.map(item => <option key={item.item_description} value={item.item_description}/>)}
    </datalist>

    <Box className="lih-sheet" ref={rootRef}>
      <table aria-label="LIH item worksheet">
        <colgroup>
          <col style={{ width: 38 }}/>
          <col style={{ width: 54 }}/>
          {COLUMNS.map(column => <col key={column.field} style={{ width: column.width }}/>)}
          <col style={{ width: 118 }}/>
          <col style={{ width: 84 }}/>
        </colgroup>
        <thead>
          <tr>
            <th scope="col" className="lih-sheet__select">
              <input
                type="checkbox"
                aria-label="Select every item on the worksheet"
                checked={allSelected}
                disabled={!rows.length}
                onChange={event => setSelected(event.target.checked ? new Set(rows.map(row => row.key)) : new Set())}
              />
            </th>
            <th scope="col" className="lih-sheet__rownum">#</th>
            {COLUMNS.map(column => <th key={column.field} scope="col" style={{ textAlign: column.align }}>
              {column.label}
            </th>)}
            <th scope="col" style={{ textAlign: 'right' }}>Total ({currency || 'amount'})</th>
            <th scope="col" className="lih-sheet__actions">Actions</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => {
            const errors: LihRowErrors = problemsByKey.get(row.key) ?? {}
            const state = rowState(row)
            return <tr key={row.key} className={rowClass(row)} data-state={state}>
              <td className="lih-sheet__select">
                <input
                  type="checkbox"
                  aria-label={`Select item ${rowIndex + 1}`}
                  checked={selected.has(row.key)}
                  onChange={event => selectRow(row.key, event.target.checked)}
                />
              </td>
              <td className="lih-sheet__rownum">
                <span className="lih-sheet__index">{rowIndex + 1}</span>
                <span className="lih-sheet__state">{state === 'new' ? 'NEW' : state === 'edited' ? 'EDIT' : 'SAVED'}</span>
              </td>
              {COLUMNS.map((column, columnIndex) => {
                const error = showErrors ? errors[column.field] : undefined
                const value = fieldValue(row, column)
                const label = `${column.label}, item ${rowIndex + 1}`
                return <td
                  key={column.field}
                  className={`lih-sheet__cell${column.align ? ` is-${column.align}` : ''}${error ? ' is-error' : ''}`}
                >
                  {column.field === 'unit'
                    ? <select
                      aria-label={label}
                      aria-invalid={Boolean(error)}
                      title={error || undefined}
                      data-row-key={row.key}
                      data-col-index={columnIndex}
                      value={value}
                      disabled={!canEdit}
                      onFocus={() => setCurrentRow(rowIndex)}
                      onChange={event => updateRow(row.key, { ...row.values, unit: event.target.value })}
                      onKeyDown={event => handleKeyDown(event, rowIndex, columnIndex)}
                    >
                      <option value="">—</option>
                      {unitOptions.map(option => <option key={option.code} value={option.code}>{option.label}</option>)}
                    </select>
                    : <input
                      aria-label={label}
                      aria-invalid={Boolean(error)}
                      title={error || undefined}
                      list={column.field === 'item_description' ? 'lih-item-suggestions' : undefined}
                      inputMode={column.numeric ? 'decimal' : undefined}
                      data-row-key={row.key}
                      data-col-index={columnIndex}
                      value={value}
                      disabled={!canEdit}
                      onFocus={() => setCurrentRow(rowIndex)}
                      onChange={event => updateRow(row.key, { ...row.values, [column.field]: event.target.value })}
                      onBlur={() => { if (column.field === 'item_description') commitDescription(row) }}
                      onKeyDown={event => handleKeyDown(event, rowIndex, columnIndex)}
                      onPaste={event => handlePaste(event, rowIndex, columnIndex)}
                    />}
                </td>
              })}
              <td className="lih-sheet__total">
                <span title={`${row.values.no_of_units || '0'} × ${row.values.unit_cost || '0'}`}>
                  {dailyMoney(lihLineTotal(row.values), currency)}
                </span>
              </td>
              <td className="lih-sheet__actions">
                <Tooltip title="Duplicate this item">
                  <span>
                    <IconButton
                      size="small"
                      aria-label={`Duplicate item ${rowIndex + 1}`}
                      disabled={!canEdit || saving}
                      onClick={() => duplicateRow(rowIndex)}
                    ><ContentCopyRounded sx={{ fontSize: 16 }}/></IconButton>
                  </span>
                </Tooltip>
                <Tooltip title="Remove this row">
                  <span>
                    <IconButton
                      size="small"
                      color="error"
                      aria-label={`Remove item ${rowIndex + 1}`}
                      disabled={!canEdit || saving}
                      onClick={() => removeRows([row.key])}
                    ><DeleteOutlineRounded sx={{ fontSize: 17 }}/></IconButton>
                  </span>
                </Tooltip>
              </td>
            </tr>
          })}
          {canEdit && <tr className="lih-sheet__addrow">
            <td colSpan={COLUMNS.length + 4}>
              <button type="button" onClick={() => addRow()} disabled={saving}>
                <AddRounded sx={{ fontSize: 16 }}/> Add item row
              </button>
            </td>
          </tr>}
        </tbody>
        <tfoot>
          <tr>
            <td colSpan={COLUMNS.length + 2}>
              {namedRows.length} item{namedRows.length === 1 ? '' : 's'} on this sheet
              {savedCount > 0 ? ` · ${savedCount} already saved` : ''}
              {removedCount > 0 ? ` · ${removedCount} to remove` : ''}
            </td>
            <td className="lih-sheet__total">{dailyMoney(sheetTotal, currency)}</td>
            <td/>
          </tr>
        </tfoot>
      </table>
    </Box>

    {showErrors && problems.length > 0 && <Alert severity="error" sx={{ mt: 1.2 }} className="lih-worksheet__problems">
      <Typography fontSize={12.5} fontWeight={800} mb={0.5}>
        Fix {problems.length} row{problems.length === 1 ? '' : 's'} before saving
      </Typography>
      <Box component="ul" sx={{ m: 0, pl: 2.2 }}>
        {problems.slice(0, 8).map(problem => <li key={problem.key}>
          <button
            type="button"
            className="lih-problem-link"
            onClick={() => focusCell(problem.key, 0)}
          >
            Row {problem.row}: {problem.message}
          </button>
        </li>)}
        {problems.length > 8 && <li>and {problems.length - 8} more row(s).</li>}
      </Box>
    </Alert>}

    {saveError && <Alert severity="error" sx={{ mt: problems.length ? 0.8 : 1.2 }}>{saveError}</Alert>}

    <Box className="lih-worksheet__foot">
      <Typography fontSize={11.5} color="text.secondary">
        Item totals are calculated as No of units × Unit cost. The day total, item count and revision are
        always recomputed by the system when the sheet is saved.
      </Typography>
      {savedCount > 0 && <Typography fontSize={11.5} color="text.secondary">
        Saved item lines stay editable: change only what differs and save the sheet again.
      </Typography>}
    </Box>
  </Box>
}

export default LihWorksheet
