import { Box, Typography } from '@mui/material'
import { navy, surface } from '../designSystem'
import { useColorMode } from '../context/ThemeContext'
import { APP_NAME, APP_TAGLINE } from '../lib/appInfo'

/**
 * The application lockup: mark, wordmark and the subtitle under it.
 *
 * `WellCost` is set in the interface ink and `IQ` carries the navy accent, so the
 * name reads as one word without needing a second colour block. The subtitle is
 * the product descriptor and is hidden nowhere it fits: it is the line that tells a
 * new user what the tool does.
 */
export default function Brand({ light = false }: { light?: boolean }) {
  const { mode } = useColorMode()
  const dark = light || mode === 'dark'
  const tone = surface(dark ? 'dark' : 'light')
  return <Box display="flex" alignItems="center" gap={1.4}>
    <Box className="brand-mark"><span className="brand-line"/><span className="brand-dot"/></Box>
    <Box>
      <Typography sx={{ display: 'block', fontFamily: 'Manrope', fontWeight: 800, letterSpacing: '-.4px', color: tone.text, lineHeight: 1.1, fontSize: 18 }}>
        WellCost<span style={{ color: dark ? navy[400] : navy[600] }}>IQ</span>
      </Typography>
      <Typography
        component="span"
        title={`${APP_NAME} — ${APP_TAGLINE}`}
        sx={{
          display: 'block',
          color: tone.textMuted,
          letterSpacing: '.1px',
          fontSize: { xs: 9, sm: 10 },
          fontWeight: 600,
          lineHeight: 1.2,
          mt: .4,
          whiteSpace: 'nowrap',
        }}
      >{APP_TAGLINE}</Typography>
    </Box>
  </Box>
}
