import { Rocket } from "lucide-react";
import { deferredFeatures } from "@/data/navigation";
import { Card } from "@/components/ui/card";

export function ComingSoonCard() {
  return (
    <Card className="p-6">
      <div className="flex items-center gap-3">
        <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-white/5 text-accent">
          <Rocket size={18} />
        </div>
        <div>
          <div className="text-lg font-semibold text-white">Deferred after backend parity pass</div>
          <div className="mt-1 text-sm text-slate-400">
            Removed from active navigation until matching backend services and API contracts exist.
          </div>
        </div>
      </div>
      <div className="mt-5 grid gap-3 md:grid-cols-2">
        {deferredFeatures.map((item) => (
          <div key={item} className="rounded-2xl border border-white/10 bg-white/[0.03] p-4 text-sm text-slate-300">
            {item}
          </div>
        ))}
      </div>
    </Card>
  );
}
