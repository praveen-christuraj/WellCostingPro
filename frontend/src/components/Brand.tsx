import { Box, Typography } from '@mui/material'
export default function Brand({ light = false }: { light?: boolean }) {
  return <Box display="flex" alignItems="center" gap={1.4}><Box className="brand-mark"><span className="brand-line"/><span className="brand-dot"/></Box><Box><Typography sx={{ fontFamily: 'Manrope', fontWeight: 800, letterSpacing: '-.7px', color: light ? 'white' : '#193646', lineHeight: 1.1, fontSize: 18 }}>wellcosting<span style={{ color: '#45c1ac' }}>.</span></Typography><Typography sx={{ color: light ? '#8baab4' : '#82939a', textTransform: 'uppercase', letterSpacing: '2.1px', fontSize: 9, fontWeight: 800, mt: .4 }}>PRO PLATFORM</Typography></Box></Box>
}
