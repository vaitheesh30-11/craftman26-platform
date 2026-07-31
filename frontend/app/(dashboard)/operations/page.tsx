import { CostTile } from "@/components/operations/cost-tile";
import { DeepTelemetryTab } from "@/components/operations/deep-telemetry-tab";
import { FindingsTile } from "@/components/operations/findings-tile";
import { HealthTile } from "@/components/operations/health-tile";
import { RevocationsTile } from "@/components/operations/revocations-tile";
import { TopPrincipalsTile } from "@/components/operations/top-principals-tile";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

export default function OperationsPage() {
  return (
    <main className="container space-y-6 py-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Operations</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Platform health, findings trend, cost, and drift -- refreshed every 60s.
        </p>
      </div>

      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="deep-telemetry">Deep telemetry</TabsTrigger>
        </TabsList>

        <TabsContent value="overview">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <FindingsTile />
            <CostTile />
            <HealthTile />
            <TopPrincipalsTile />
            <RevocationsTile />
          </div>
        </TabsContent>

        <TabsContent value="deep-telemetry">
          <DeepTelemetryTab />
        </TabsContent>
      </Tabs>
    </main>
  );
}
