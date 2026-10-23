import UsageReportShell from '../../components/reports/UsageReportShell'
import { reportDefinition } from '../../lib/usageReports'

const definition = reportDefinition('services')

export default function ServiceWiseCostReport() {
  return <UsageReportShell
    reportKey="services"
    title={definition.title}
    eyebrow={definition.eyebrow}
    subtitle={definition.subtitle}
    matrixTitle="Service cost matrix — total costs only"
    matrixHint="Services are rows; each well column shows section-wise and total service costs for the selected filters."
  />
}
