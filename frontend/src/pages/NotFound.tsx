import { Box, Button, Paper, Typography } from '@mui/material'
import { ArrowBackRounded, DashboardOutlined, SearchOffRounded } from '@mui/icons-material'
import { Link as RouterLink, useLocation, useNavigate } from 'react-router-dom'
import { PageHeading } from '../components/Common'
import { useAuth } from '../context/AuthContext'

/**
 * Unknown address inside the application.
 *
 * Without this page the router silently dropped the user on the landing page,
 * which reads as "my bookmark does not work any more". Naming the address that
 * was asked for — and offering the two places people actually want next — turns
 * a dead end into a one-click recovery. It also repeats the rule from the API's
 * 404 handler: a URL that used to work usually means the page bundle and the
 * deployment are out of step.
 */
export default function NotFound() {
  const location = useLocation()
  const navigate = useNavigate()
  const { can } = useAuth()
  const home = can('rig-well:read') || can('afe:read') || can('daily-cost:read') ? '/business-dashboard' : '/dashboard'

  return <>
    <PageHeading
      eyebrow="WELLCOSTIQ / PAGE NOT FOUND"
      title="This page does not exist"
      subtitle="The address was not recognised, so nothing was loaded or changed. Pick a destination below, or check the link you followed."
    />
    <Paper variant="outlined" sx={{ borderRadius: 2, p: { xs: 2.5, sm: 4 }, maxWidth: 760 }}>
      <Box display="flex" alignItems="flex-start" gap={2}>
        <Box className="stat-icon" sx={{ color: 'text.secondary', bgcolor: 'action.hover', width: 40, height: 40, flexShrink: 0 }}>
          <SearchOffRounded sx={{ fontSize: 20 }}/>
        </Box>
        <Box minWidth={0}>
          <Typography fontSize={13} fontWeight={750} mb={.5}>What was requested</Typography>
          <Typography
            component="code"
            sx={{ display: 'block', fontFamily: 'var(--wcp-font-mono, monospace)', fontSize: 12.5, wordBreak: 'break-all' }}
          >
            {location.pathname}{location.search}
          </Typography>
          <Typography color="text.secondary" fontSize={12.5} sx={{ mt: 1.6, lineHeight: 1.6 }}>
            A page that worked before and fails now usually means the browser kept an older copy of the
            application than the one deployed. Reload the page first; if the address still fails, it was
            renamed or removed and an administrator can tell you where the screen moved to.
          </Typography>
          <Box display="flex" gap={1} flexWrap="wrap" mt={2.5}>
            <Button variant="contained" startIcon={<DashboardOutlined/>} component={RouterLink} to={home}>
              Go to the dashboard
            </Button>
            <Button startIcon={<ArrowBackRounded/>} onClick={() => navigate(-1)}>Back to the previous page</Button>
            <Button color="inherit" onClick={() => window.location.reload()}>Reload</Button>
          </Box>
        </Box>
      </Box>
    </Paper>
  </>
}
