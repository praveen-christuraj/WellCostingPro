import UsageReportShell from '../../components/reports/UsageReportShell'
import { reportDefinition } from '../../lib/usageReports'

const definition = reportDefinition('tangibles')

export default function TangiblesUsageReport() {
  return <UsageReportShell
    reportKey="tangibles"
    title={definition.title}
    eyebrow={definition.eyebrow}
    subtitle={definition.subtitle}
    matrixTitle="Tangible usage matrix — categorized by catalogue groups"
    matrixHint="Tangibles are rows banded by category and subcategory; each well column shows section-wise usage quantity and cost."
  />
}
