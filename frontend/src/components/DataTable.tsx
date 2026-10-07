import { useMemo, useState } from 'react'
import { Box, InputAdornment, Paper, TextField, Typography } from '@mui/material'
import { SearchRounded } from '@mui/icons-material'
import { AgGridReact } from 'ag-grid-react'
import { AllCommunityModule, ModuleRegistry, themeQuartz, type ColDef } from 'ag-grid-community'
ModuleRegistry.registerModules([AllCommunityModule])
export const gridTheme = themeQuartz.withParams({ accentColor: '#0d756e', backgroundColor: '#ffffff', borderColor: '#e9eef0', foregroundColor: '#243d49', headerBackgroundColor: '#f9fbfb', headerFontWeight: 700, fontFamily: 'DM Sans, sans-serif', fontSize: 12, rowHoverColor: '#f4faf8', spacing: 10 })
export function DataTable<T extends object>({ rows, columns, searchPlaceholder = 'Search records...' }: { rows: T[]; columns: ColDef<T>[]; searchPlaceholder?: string }) {
  const [search, setSearch] = useState('')
  const visible = useMemo(() => rows.filter(row => JSON.stringify(row).toLowerCase().includes(search.toLowerCase())), [rows, search])
  return <Paper variant="outlined" sx={{ borderColor: 'divider', overflow: 'hidden', borderRadius: 2 }}><Box display="flex" justifyContent="space-between" alignItems="center" sx={{ p: 2.2, gap: 2, flexWrap: 'wrap' }}><TextField placeholder={searchPlaceholder} value={search} onChange={e => setSearch(e.target.value)} size="small" sx={{ width: { xs: '100%', sm: 285 }, '& .MuiOutlinedInput-root': { bgcolor: '#fafcfc' } }} InputProps={{ startAdornment: <InputAdornment position="start"><SearchRounded sx={{ color: '#9aaab1', fontSize: 19 }}/></InputAdornment> }}/><Typography fontSize={12} color="text.secondary">{visible.length} {visible.length === 1 ? 'record' : 'records'}</Typography></Box><Box sx={{ height: Math.min(600, Math.max(270, 57 + visible.length * 55)), width: '100%' }}><AgGridReact<T> theme={gridTheme} rowData={visible} columnDefs={columns} defaultColDef={{ sortable: true, resizable: true, flex: 1, minWidth: 120 }} rowHeight={55} headerHeight={48} pagination={visible.length > 8} paginationPageSize={8} paginationPageSizeSelector={false} getRowId={p => (p.data as { id: string }).id} overlayNoRowsTemplate="No records found" suppressCellFocus/></Box></Paper>
}
