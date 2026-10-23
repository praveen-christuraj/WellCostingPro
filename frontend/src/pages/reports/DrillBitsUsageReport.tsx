import UsageReportShell from '../../components/reports/UsageReportShell'
import { reportDefinition } from '../../lib/usageReports'

const definition = reportDefinition('drill-bits')

export default function DrillBitsUsageReport() {
  return <UsageReportShell
    reportKey="drill-bits"
    title={definition.title}
    eyebrow={definition.eyebrow}
    subtitle={definition.subtitle}
    matrixTitle="Drill bit usage matrix — make, model and size"
    matrixHint="Drill bits are rows with make details; each well column shows section-wise usage quantity and cost, then the well total."
  />
}
