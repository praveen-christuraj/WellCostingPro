import UsageReportShell from '../../components/reports/UsageReportShell'
import { reportDefinition } from '../../lib/usageReports'

const definition = reportDefinition('vendors')

export default function VendorWiseCostReport() {
  return <UsageReportShell
    reportKey="vendors"
    title={definition.title}
    eyebrow={definition.eyebrow}
    subtitle={definition.subtitle}
    matrixTitle="Vendor / company cost matrix — total costs only"
    matrixHint="Vendors and recorded companies are rows; each well column shows section-wise costs spanning services, consumables, tangibles and other expenses."
  />
}
