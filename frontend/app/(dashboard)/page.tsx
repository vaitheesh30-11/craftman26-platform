import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

const FEATURES = [
  { id: "F1", name: "PassRole Blast Radius" },
  { id: "F2", name: "Org-Context Policy Validator" },
  { id: "F3", name: "S3 Data Event Enricher" },
  { id: "F4", name: "SCP Change Impact Analyzer" },
  { id: "F5", name: "SSO Emergency Session Killer" },
  { id: "F6", name: "Management Account Shadow Guard" },
  { id: "F7", name: "SCP Collision Resolver" },
  { id: "F8", name: "SLR Breakage Pre-Scanner" },
] as const;

export default function DashboardPage() {
  return (
    <main className="container py-10">
      <h1 className="text-2xl font-semibold tracking-tight">IAM Sentinel</h1>
      <p className="mt-1 text-muted-foreground">
        Eight specialist agents watching for the IAM/SCP gaps AWS documentation itself acknowledges.
      </p>
      <div className="mt-8 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {FEATURES.map((feature) => (
          <Card key={feature.id}>
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between">
                <Badge variant="secondary">{feature.id}</Badge>
              </div>
            </CardHeader>
            <CardContent>
              <CardTitle className="text-base">{feature.name}</CardTitle>
              <CardDescription className="mt-1">Specialist ready.</CardDescription>
            </CardContent>
          </Card>
        ))}
      </div>
    </main>
  );
}
