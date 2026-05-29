import Image from "next/image";
import Link from "next/link";
import { cn } from "@/lib/utils";

/** CostAssist wordmark — official CoFab molecular-network icon + "CoFab"
 *  with the "CostAssist CNC Costing Agent" product label beneath. The icon
 *  is the cropped pentagon-star glyph from the company logo deck
 *  (public/cofab-icon.png, transparent background, 1075x1016 source). */
export function BrandMark({
  className,
  href = "/",
  subtitle = "Connecting Fabricators",
}: {
  className?: string;
  href?: string | null;
  subtitle?: string | null;
}) {
  const inner = (
    <span className={cn("flex items-center gap-2.5", className)}>
      <Image
        src="/cofab-icon.png"
        alt="CoFab"
        width={32}
        height={32}
        className="h-8 w-8 shrink-0 object-contain"
        priority
      />
      <span className="flex min-w-0 flex-col leading-none">
        <span className="text-[17px] font-bold tracking-tight text-blue-600">CoFab</span>
        {subtitle && (
          <span className="mt-1 text-[11px] italic font-medium leading-tight tracking-tight text-blue-600/80">
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
