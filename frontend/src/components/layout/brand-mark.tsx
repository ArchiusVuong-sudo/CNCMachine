import Link from "next/link";
import { Box } from "lucide-react";
import { cn } from "@/lib/utils";

/** CoFab wordmark — blue gradient cube tile + "CoFab" in brand blue. */
export function BrandMark({
  className,
  href = "/",
  subtitle = "CNC Costing",
}: {
  className?: string;
  href?: string | null;
  subtitle?: string | null;
}) {
  const inner = (
    <span className={cn("flex items-center gap-2.5", className)}>
      <span className="brand-gradient flex h-8 w-8 items-center justify-center rounded-lg shadow-sm">
        <Box className="h-4.5 w-4.5 text-white" strokeWidth={2.25} />
      </span>
      <span className="flex flex-col leading-none">
        <span className="text-[17px] font-bold tracking-tight text-blue-600">CoFab</span>
        {subtitle && (
          <span className="mt-0.5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
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
