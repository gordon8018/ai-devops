import { cva, type VariantProps } from "class-variance-authority";
import { HTMLAttributes } from "react";
import { cn } from "../../lib/cn";

const badgeVariants = cva("badge", {
  variants: {
    variant: {
      default:   "badge-default",
      queued:    "badge-queued",
      planning:  "badge-planning",
      running:   "badge-running",
      blocked:   "badge-blocked",
      ready:     "badge-ready",
      released:  "badge-released",
      closed:    "badge-closed",
      critical:  "badge-critical",
      high:      "badge-high",
      medium:    "badge-medium",
      low:       "badge-low",
    },
  },
  defaultVariants: { variant: "default" },
});

export type BadgeVariant = NonNullable<VariantProps<typeof badgeVariants>["variant"]>;

export interface BadgeProps
  extends HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}
