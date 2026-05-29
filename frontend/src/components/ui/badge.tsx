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
        destructive: "bg-red-50 text-red-700 border border-red-200",
        outline:     "text-foreground border-border",
        success:     "bg-emerald-50 text-emerald-700 border border-emerald-200",
        warning:     "bg-amber-50 text-amber-700 border border-amber-200",
        info:        "bg-primary/10 text-primary border border-primary/25",
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
