import UsageReportShell from '../../components/reports/UsageReportShell'
import { reportDefinition } from '../../lib/usageReports'

const definition = reportDefinition('mud-chemicals')

export default function MudChemicalsUsageReport() {
  return <UsageReportShell
    reportKey="mud-chemicals"
    title={definition.title}
    eyebrow={definition.eyebrow}
    subtitle={definition.subtitle}
    matrixTitle="Chemical usage matrix — wells and hole sections"
    matrixHint="Chemicals are rows; each well column shows section-wise usage quantity and cost, then the well total."
  />
}
