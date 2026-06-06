import type { LucideIcon } from "lucide-react";

interface KpiCardProps {
  title: string;
  value: string | number;
  status: string;
  icon: LucideIcon;
}

export default function KpiCard({
  title,
  value,
  status,
  icon: Icon,
}: KpiCardProps) {
  return (
    <section className="card kpi-card">
      <div className="kpi-card-top">
        <span className="kpi-title">{title}</span>
        <span className="kpi-icon" aria-hidden="true">
          <Icon size={18} strokeWidth={2.2} />
        </span>
      </div>
      <strong className="kpi-value">{value}</strong>
      <span className="kpi-status">{status}</span>
    </section>
  );
}
