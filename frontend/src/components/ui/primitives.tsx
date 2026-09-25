/* Small shadcn-style primitives: Card, Badge, Input, Textarea, Label, Separator, Skeleton,
   Progress, Switch, Checkbox, Alert, Table. Radix provides behaviour and accessibility. */
import { cva, type VariantProps } from 'class-variance-authority'
import { Checkbox as CheckboxPrimitive, Label as LabelPrimitive, Progress as ProgressPrimitive, Separator as SeparatorPrimitive, Switch as SwitchPrimitive } from 'radix-ui'
import { CheckIcon } from 'lucide-react'
import * as React from 'react'

import { cn } from '@/lib/utils'

// ---------------------------------------------------------------- card
export function Card({ className, ...props }: React.ComponentProps<'div'>) {
  return <div data-slot="card" className={cn('bg-card text-card-foreground flex flex-col gap-4 rounded-xl border py-5 shadow-xs', className)} {...props} />
}
export function CardHeader({ className, ...props }: React.ComponentProps<'div'>) {
  return <div data-slot="card-header" className={cn('grid auto-rows-min items-start gap-1 px-5 has-data-[slot=card-action]:grid-cols-[1fr_auto]', className)} {...props} />
}
export function CardTitle({ className, ...props }: React.ComponentProps<'h3'>) {
  return <h3 data-slot="card-title" className={cn('text-base leading-none font-semibold tracking-tight', className)} {...props} />
}
export function CardDescription({ className, ...props }: React.ComponentProps<'p'>) {
  return <p data-slot="card-description" className={cn('text-muted-foreground text-sm', className)} {...props} />
}
export function CardAction({ className, ...props }: React.ComponentProps<'div'>) {
  return <div data-slot="card-action" className={cn('col-start-2 row-span-2 row-start-1 self-start justify-self-end', className)} {...props} />
}
export function CardContent({ className, ...props }: React.ComponentProps<'div'>) {
  return <div data-slot="card-content" className={cn('px-5', className)} {...props} />
}
export function CardFooter({ className, ...props }: React.ComponentProps<'div'>) {
  return <div data-slot="card-footer" className={cn('flex items-center px-5', className)} {...props} />
}

// ---------------------------------------------------------------- badge
export const badgeVariants = cva(
  'inline-flex items-center justify-center rounded-md border px-2 py-0.5 text-xs font-medium w-fit whitespace-nowrap shrink-0 [&>svg]:size-3 gap-1 [&>svg]:pointer-events-none transition-colors',
  {
    variants: {
      variant: {
        default: 'border-transparent bg-primary text-primary-foreground',
        secondary: 'border-transparent bg-secondary text-secondary-foreground',
        outline: 'text-foreground',
        success: 'border-success/25 bg-success/12 text-success dark:text-success',
        warning: 'border-warning/35 bg-warning/15 text-[oklch(0.45_0.12_60)] dark:text-warning',
        destructive: 'border-destructive/25 bg-destructive/10 text-destructive',
        info: 'border-info/25 bg-info/10 text-info',
        primary: 'border-primary/20 bg-primary/10 text-primary',
        validate: 'border-validate/25 bg-validate/10 text-validate',
        muted: 'border-transparent bg-muted text-muted-foreground',
      },
    },
    defaultVariants: { variant: 'default' },
  },
)
export function Badge({ className, variant, ...props }: React.ComponentProps<'span'> & VariantProps<typeof badgeVariants>) {
  return <span data-slot="badge" className={cn(badgeVariants({ variant }), className)} {...props} />
}

// ---------------------------------------------------------------- inputs
export function Input({ className, type, ...props }: React.ComponentProps<'input'>) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        'file:text-foreground placeholder:text-muted-foreground selection:bg-primary selection:text-primary-foreground border-input flex h-9 w-full min-w-0 rounded-lg border bg-card px-3 py-1 text-sm shadow-xs transition-[color,box-shadow] outline-none file:inline-flex file:h-7 file:border-0 file:bg-transparent file:text-sm file:font-medium disabled:cursor-not-allowed disabled:opacity-50',
        'focus-visible:border-ring focus-visible:ring-ring/30 focus-visible:ring-[3px]',
        'aria-invalid:ring-destructive/20 aria-invalid:border-destructive',
        className,
      )}
      {...props}
    />
  )
}
export function Textarea({ className, ...props }: React.ComponentProps<'textarea'>) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(
        'border-input placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/30 aria-invalid:ring-destructive/20 aria-invalid:border-destructive flex field-sizing-content min-h-20 w-full rounded-lg border bg-card px-3 py-2 text-sm shadow-xs transition-[color,box-shadow] outline-none focus-visible:ring-[3px] disabled:cursor-not-allowed disabled:opacity-50',
        className,
      )}
      {...props}
    />
  )
}
export function Label({ className, ...props }: React.ComponentProps<typeof LabelPrimitive.Root>) {
  return <LabelPrimitive.Root data-slot="label" className={cn('flex items-center gap-2 text-sm leading-none font-medium select-none peer-disabled:opacity-50', className)} {...props} />
}
export function NativeSelect({ className, ...props }: React.ComponentProps<'select'>) {
  return (
    <select
      data-slot="native-select"
      className={cn(
        'border-input flex h-9 w-full rounded-lg border bg-card px-3 py-1 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-ring/30 focus-visible:ring-[3px] aria-invalid:border-destructive disabled:opacity-50',
        className,
      )}
      {...props}
    />
  )
}

// ---------------------------------------------------------------- misc
export function Separator({ className, orientation = 'horizontal', decorative = true, ...props }: React.ComponentProps<typeof SeparatorPrimitive.Root>) {
  return (
    <SeparatorPrimitive.Root
      data-slot="separator"
      decorative={decorative}
      orientation={orientation}
      className={cn('bg-border shrink-0 data-[orientation=horizontal]:h-px data-[orientation=horizontal]:w-full data-[orientation=vertical]:h-full data-[orientation=vertical]:w-px', className)}
      {...props}
    />
  )
}
export function Skeleton({ className, ...props }: React.ComponentProps<'div'>) {
  return <div data-slot="skeleton" aria-hidden className={cn('skeleton-shimmer rounded-md', className)} {...props} />
}
export function Progress({ className, value, indicatorClassName, ...props }: React.ComponentProps<typeof ProgressPrimitive.Root> & { indicatorClassName?: string }) {
  return (
    <ProgressPrimitive.Root data-slot="progress" className={cn('bg-muted relative h-2 w-full overflow-hidden rounded-full', className)} value={value} {...props}>
      <ProgressPrimitive.Indicator className={cn('bg-primary h-full w-full flex-1 transition-all', indicatorClassName)} style={{ transform: `translateX(-${100 - (value || 0)}%)` }} />
    </ProgressPrimitive.Root>
  )
}
export function Switch({ className, ...props }: React.ComponentProps<typeof SwitchPrimitive.Root>) {
  return (
    <SwitchPrimitive.Root
      data-slot="switch"
      className={cn('peer data-[state=checked]:bg-primary data-[state=unchecked]:bg-input focus-visible:ring-ring/40 inline-flex h-5 w-9 shrink-0 items-center rounded-full border border-transparent shadow-xs transition-all outline-none focus-visible:ring-[3px] disabled:cursor-not-allowed disabled:opacity-50', className)}
      {...props}
    >
      <SwitchPrimitive.Thumb className="bg-background pointer-events-none block size-4 rounded-full ring-0 transition-transform data-[state=checked]:translate-x-[calc(100%-2px)] data-[state=unchecked]:translate-x-0.5" />
    </SwitchPrimitive.Root>
  )
}
export function Checkbox({ className, ...props }: React.ComponentProps<typeof CheckboxPrimitive.Root>) {
  return (
    <CheckboxPrimitive.Root
      data-slot="checkbox"
      className={cn('peer border-input data-[state=checked]:bg-primary data-[state=checked]:text-primary-foreground data-[state=checked]:border-primary focus-visible:ring-ring/40 size-4 shrink-0 rounded-[4px] border shadow-xs outline-none focus-visible:ring-[3px] disabled:opacity-50', className)}
      {...props}
    >
      <CheckboxPrimitive.Indicator className="flex items-center justify-center text-current">
        <CheckIcon className="size-3.5" />
      </CheckboxPrimitive.Indicator>
    </CheckboxPrimitive.Root>
  )
}

// ---------------------------------------------------------------- alert
const alertVariants = cva('relative w-full rounded-xl border px-4 py-3 text-sm grid has-[>svg]:grid-cols-[calc(var(--spacing)*4)_1fr] grid-cols-[0_1fr] has-[>svg]:gap-x-3 gap-y-0.5 items-start [&>svg]:size-4 [&>svg]:translate-y-0.5 [&>svg]:text-current', {
  variants: {
    variant: {
      default: 'bg-card text-card-foreground',
      destructive: 'border-destructive/30 bg-destructive/6 text-destructive [&>div]:text-destructive/90',
      warning: 'border-warning/40 bg-warning/10 text-[oklch(0.42_0.11_60)] dark:text-warning',
      success: 'border-success/30 bg-success/8 text-success',
      info: 'border-info/30 bg-info/8 text-info',
    },
  },
  defaultVariants: { variant: 'default' },
})
export function Alert({ className, variant, ...props }: React.ComponentProps<'div'> & VariantProps<typeof alertVariants>) {
  return <div data-slot="alert" role="alert" className={cn(alertVariants({ variant }), className)} {...props} />
}
export function AlertTitle({ className, ...props }: React.ComponentProps<'div'>) {
  return <div data-slot="alert-title" className={cn('col-start-2 line-clamp-1 min-h-4 font-semibold tracking-tight', className)} {...props} />
}
export function AlertDescription({ className, ...props }: React.ComponentProps<'div'>) {
  return <div data-slot="alert-description" className={cn('col-start-2 grid justify-items-start gap-1 text-sm opacity-90 [&_p]:leading-relaxed', className)} {...props} />
}

// ---------------------------------------------------------------- table
export function Table({ className, ...props }: React.ComponentProps<'table'>) {
  return (
    <div data-slot="table-container" className="relative w-full overflow-x-auto scrollbar-thin">
      <table data-slot="table" className={cn('w-full caption-bottom text-sm', className)} {...props} />
    </div>
  )
}
export function TableHeader({ className, ...props }: React.ComponentProps<'thead'>) {
  return <thead data-slot="table-header" className={cn('[&_tr]:border-b bg-muted/40', className)} {...props} />
}
export function TableBody({ className, ...props }: React.ComponentProps<'tbody'>) {
  return <tbody data-slot="table-body" className={cn('[&_tr:last-child]:border-0', className)} {...props} />
}
export function TableRow({ className, ...props }: React.ComponentProps<'tr'>) {
  return <tr data-slot="table-row" className={cn('hover:bg-muted/40 data-[state=selected]:bg-muted border-b transition-colors', className)} {...props} />
}
export function TableHead({ className, ...props }: React.ComponentProps<'th'>) {
  return <th data-slot="table-head" className={cn('text-muted-foreground h-10 px-3 text-left align-middle text-xs font-semibold uppercase tracking-wide whitespace-nowrap', className)} {...props} />
}
export function TableCell({ className, ...props }: React.ComponentProps<'td'>) {
  return <td data-slot="table-cell" className={cn('px-3 py-2.5 align-middle', className)} {...props} />
}
