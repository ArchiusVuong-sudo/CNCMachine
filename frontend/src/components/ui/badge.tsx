import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-md border px-2.5 py-0.5 text-xs font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2",
  {
    variants: {
      variant: {
        default:     "border-transparent bg-primary text-primary-foreground shadow",
        secondary:   "border-transparent bg-secondary text-secondary-foreground",
        destructive: "bg-red-500/15 text-red-400 border border-red-500/25",
        outline:     "text-foreground border-border",
        success:     "bg-emerald-500/15 text-emerald-400 border border-emerald-500/25",
        warning:     "bg-amber-500/15 text-amber-400 border border-amber-500/25",
        info:        "bg-blue-500/15 text-blue-400 border border-blue-500/25",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
);

function Badge({
  className,
  variant,
  ...props
}: React.ComponentProps<"div"> & VariantProps<typeof badgeVariants>) {
  return (
    <div className={cn(badgeVariants({ variant }), className)} {...props} />
  );
}

export { Badge, badgeVariants };
