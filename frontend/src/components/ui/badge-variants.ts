import { cva } from "class-variance-authority"

/** critical = red, warning = amber: severity only. default = the single accent. */
export const badgeVariants = cva(
  "inline-flex w-fit shrink-0 items-center justify-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium whitespace-nowrap transition-colors [&>svg]:size-3 [&>svg]:pointer-events-none",
  {
    variants: {
      variant: {
        default: "border-transparent bg-primary-soft text-primary-soft-foreground",
        secondary: "border-transparent bg-secondary text-secondary-foreground",
        outline: "border-border bg-card text-muted-foreground",
        critical:
          "border-alert-critical/25 bg-alert-critical-soft text-alert-critical-text",
        warning:
          "border-alert-warning/40 bg-alert-warning-soft text-alert-warning-text",
      },
    },
    defaultVariants: { variant: "default" },
  }
)
