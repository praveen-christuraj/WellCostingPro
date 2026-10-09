import { Box, Typography } from '@mui/material'
import { useColorMode } from '../context/ThemeContext'
export default function Brand({ light = false }: { light?: boolean }) {
  const { mode } = useColorMode()
  const dark = light || mode === 'dark'
  return <Box display="flex" alignItems="center" gap={1.4}><Box className="brand-mark"><span className="brand-line"/><span className="brand-dot"/></Box><Box><Typography sx={{ fontFamily: 'Manrope', fontWeight: 800, letterSpacing: '-.7px', color: dark ? 'white' : '#123A63', lineHeight: 1.1, fontSize: 18 }}>wellcosting<span style={{ color: dark ? '#8FB8E4' : '#123A63', opacity: dark ? 1 : .65 }}>.</span></Typography><Typography sx={{ color: dark ? '#A7B8CB' : '#5B6B7F', textTransform: 'uppercase', letterSpacing: '2.1px', fontSize: 9, fontWeight: 800, mt: .4 }}>PRO PLATFORM</Typography></Box></Box>
}
