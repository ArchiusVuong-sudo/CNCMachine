import Link from "next/link";
import { Box } from "lucide-react";
import { cn } from "@/lib/utils";

/** CostAssist wordmark — blue gradient cube tile + "CoFab" with the
 *  "CostAssist CNC Costing Agent" product label beneath. */
export function BrandMark({
  className,
  href = "/",
  subtitle = "CostAssist CNC Costing Agent",
}: {
  className?: string;
  href?: string | null;
  subtitle?: string | null;
}) {
  const inner = (
    <span className={cn("flex items-center gap-2.5", className)}>
      <span className="brand-gradient flex h-8 w-8 shrink-0 items-center justify-center rounded-lg shadow-sm">
        <Box className="h-4.5 w-4.5 text-white" strokeWidth={2.25} />
      </span>
      <span className="flex min-w-0 flex-col leading-none">
        <span className="text-[17px] font-bold tracking-tight text-blue-600">CoFab</span>
        {subtitle && (
          <span className="mt-1 text-[10px] font-medium leading-tight tracking-tight text-muted-foreground">
            {subtitle}
          </span>
        )}
      </span>
    </span>
  );

  if (!href) return inner;
  return (
    <Link href={href} className="shrink-0 outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-lg">
      {inner}
    </Link>
  );
}
