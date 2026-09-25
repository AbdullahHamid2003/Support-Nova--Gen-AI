/* Radix-based overlay & navigation primitives: Dialog, Sheet, DropdownMenu, Tabs, Tooltip,
   Popover, Select, ScrollArea. Focus trapping, escape handling and ARIA come from Radix. */
import { Dialog as DialogPrimitive, DropdownMenu as MenuPrimitive, Popover as PopoverPrimitive, ScrollArea as ScrollAreaPrimitive, Select as SelectPrimitive, Tabs as TabsPrimitive, Tooltip as TooltipPrimitive } from 'radix-ui'
import { CheckIcon, ChevronDownIcon, XIcon } from 'lucide-react'
import * as React from 'react'

import { cn } from '@/lib/utils'

// ---------------------------------------------------------------- dialog
export const Dialog = DialogPrimitive.Root
export const DialogTrigger = DialogPrimitive.Trigger
export const DialogClose = DialogPrimitive.Close

export function DialogContent({ className, children, showClose = true, ...props }: React.ComponentProps<typeof DialogPrimitive.Content> & { showClose?: boolean }) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="data-[state=open]:animate-in data-[state=closed]:animate-out fixed inset-0 z-50 bg-black/45 backdrop-blur-[2px]" />
      <DialogPrimitive.Content
        data-slot="dialog-content"
        className={cn(
          'bg-popover text-popover-foreground fixed top-1/2 left-1/2 z-50 grid max-h-[90vh] w-[calc(100%-2rem)] max-w-lg -translate-x-1/2 -translate-y-1/2 gap-4 overflow-y-auto rounded-xl border p-6 shadow-2xl outline-none',
          className,
        )}
        {...props}
      >
        {children}
        {showClose && (
          <DialogPrimitive.Close className="ring-offset-background focus-visible:ring-ring absolute top-4 right-4 rounded-md p-1 opacity-70 transition-opacity hover:opacity-100 focus-visible:ring-2 focus:outline-none">
            <XIcon className="size-4" />
            <span className="sr-only">Close</span>
          </DialogPrimitive.Close>
        )}
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  )
}
export function DialogHeader({ className, ...props }: React.ComponentProps<'div'>) {
  return <div className={cn('flex flex-col gap-1.5 pr-6', className)} {...props} />
}
export function DialogFooter({ className, ...props }: React.ComponentProps<'div'>) {
  return <div className={cn('flex flex-col-reverse gap-2 sm:flex-row sm:justify-end', className)} {...props} />
}
export function DialogTitle({ className, ...props }: React.ComponentProps<typeof DialogPrimitive.Title>) {
  return <DialogPrimitive.Title className={cn('text-lg leading-tight font-semibold', className)} {...props} />
}
export function DialogDescription({ className, ...props }: React.ComponentProps<typeof DialogPrimitive.Description>) {
  return <DialogPrimitive.Description className={cn('text-muted-foreground text-sm', className)} {...props} />
}

// ---------------------------------------------------------------- sheet (side panel)
export const Sheet = DialogPrimitive.Root
export const SheetTrigger = DialogPrimitive.Trigger
export function SheetContent({ className, children, side = 'left', ...props }: React.ComponentProps<typeof DialogPrimitive.Content> & { side?: 'left' | 'right' }) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/45" />
      <DialogPrimitive.Content
        className={cn('fixed inset-y-0 z-50 flex h-full w-[86%] max-w-sm flex-col shadow-2xl outline-none', side === 'left' ? 'left-0' : 'right-0', className)}
        {...props}
      >
        {children}
        <DialogPrimitive.Close className="absolute top-4 right-4 rounded-md p-1 opacity-70 hover:opacity-100">
          <XIcon className="size-4" />
          <span className="sr-only">Close</span>
        </DialogPrimitive.Close>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  )
}
export const SheetTitle = DialogPrimitive.Title
export const SheetDescription = DialogPrimitive.Description

// ---------------------------------------------------------------- dropdown menu
export const DropdownMenu = MenuPrimitive.Root
export const DropdownMenuTrigger = MenuPrimitive.Trigger
export function DropdownMenuContent({ className, sideOffset = 6, ...props }: React.ComponentProps<typeof MenuPrimitive.Content>) {
  return (
    <MenuPrimitive.Portal>
      <MenuPrimitive.Content
        sideOffset={sideOffset}
        className={cn('bg-popover text-popover-foreground z-50 min-w-[10rem] overflow-hidden rounded-lg border p-1 shadow-lg', className)}
        {...props}
      />
    </MenuPrimitive.Portal>
  )
}
export function DropdownMenuItem({ className, inset, ...props }: React.ComponentProps<typeof MenuPrimitive.Item> & { inset?: boolean }) {
  return (
    <MenuPrimitive.Item
      className={cn(
        "focus:bg-accent focus:text-accent-foreground relative flex cursor-default items-center gap-2 rounded-md px-2 py-1.5 text-sm outline-hidden select-none data-[disabled]:pointer-events-none data-[disabled]:opacity-50 [&_svg:not([class*='size-'])]:size-4",
        inset && 'pl-8',
        className,
      )}
      {...props}
    />
  )
}
export function DropdownMenuLabel({ className, ...props }: React.ComponentProps<typeof MenuPrimitive.Label>) {
  return <MenuPrimitive.Label className={cn('px-2 py-1.5 text-sm font-medium', className)} {...props} />
}
export function DropdownMenuSeparator({ className, ...props }: React.ComponentProps<typeof MenuPrimitive.Separator>) {
  return <MenuPrimitive.Separator className={cn('bg-border -mx-1 my-1 h-px', className)} {...props} />
}

// ---------------------------------------------------------------- tabs
export function Tabs({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Root>) {
  return <TabsPrimitive.Root className={cn('flex flex-col gap-4', className)} {...props} />
}
export function TabsList({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.List>) {
  return (
    <TabsPrimitive.List
      className={cn('bg-muted text-muted-foreground inline-flex h-10 w-fit max-w-full items-center justify-start gap-0.5 overflow-x-auto rounded-lg p-1 scrollbar-thin', className)}
      {...props}
    />
  )
}
export function TabsTrigger({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Trigger>) {
  return (
    <TabsPrimitive.Trigger
      className={cn(
        "data-[state=active]:bg-card data-[state=active]:text-foreground data-[state=active]:shadow-sm focus-visible:ring-ring/40 inline-flex h-full items-center justify-center gap-1.5 rounded-md px-3 text-sm font-medium whitespace-nowrap transition-all focus-visible:ring-[3px] focus-visible:outline-none disabled:pointer-events-none disabled:opacity-50 [&_svg:not([class*='size-'])]:size-4 cursor-pointer",
        className,
      )}
      {...props}
    />
  )
}
export function TabsContent({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Content>) {
  return <TabsPrimitive.Content className={cn('flex-1 outline-none', className)} {...props} />
}

// ---------------------------------------------------------------- tooltip
export const TooltipProvider = TooltipPrimitive.Provider
export function Tooltip({ children, content, side = 'top' }: { children: React.ReactNode; content: React.ReactNode; side?: 'top' | 'bottom' | 'left' | 'right' }) {
  if (!content) return <>{children}</>
  return (
    <TooltipPrimitive.Root delayDuration={200}>
      <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content side={side} sideOffset={6} className="bg-foreground text-background z-50 max-w-xs rounded-md px-2.5 py-1.5 text-xs leading-snug shadow-lg">
          {content}
          <TooltipPrimitive.Arrow className="fill-foreground" />
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  )
}

// ---------------------------------------------------------------- popover
export const Popover = PopoverPrimitive.Root
export const PopoverTrigger = PopoverPrimitive.Trigger
export function PopoverContent({ className, align = 'start', sideOffset = 6, ...props }: React.ComponentProps<typeof PopoverPrimitive.Content>) {
  return (
    <PopoverPrimitive.Portal>
      <PopoverPrimitive.Content align={align} sideOffset={sideOffset} className={cn('bg-popover text-popover-foreground z-50 w-72 rounded-lg border p-4 shadow-lg outline-hidden', className)} {...props} />
    </PopoverPrimitive.Portal>
  )
}

// ---------------------------------------------------------------- select
export function Select({ value, onValueChange, placeholder, options, className, id, disabled, 'aria-label': ariaLabel }: {
  value?: string
  onValueChange: (v: string) => void
  placeholder?: string
  options: { value: string; label: string }[]
  className?: string
  id?: string
  disabled?: boolean
  'aria-label'?: string
}) {
  return (
    <SelectPrimitive.Root value={value || undefined} onValueChange={onValueChange} disabled={disabled}>
      <SelectPrimitive.Trigger
        id={id}
        aria-label={ariaLabel}
        className={cn('border-input data-[placeholder]:text-muted-foreground flex h-9 w-full items-center justify-between gap-2 rounded-lg border bg-card px-3 py-2 text-sm whitespace-nowrap shadow-xs outline-none focus-visible:border-ring focus-visible:ring-ring/30 focus-visible:ring-[3px] disabled:opacity-50 cursor-pointer [&>span]:truncate', className)}
      >
        <SelectPrimitive.Value placeholder={placeholder} />
        <SelectPrimitive.Icon asChild>
          <ChevronDownIcon className="size-4 opacity-50" />
        </SelectPrimitive.Icon>
      </SelectPrimitive.Trigger>
      <SelectPrimitive.Portal>
        <SelectPrimitive.Content position="popper" sideOffset={4} className="bg-popover text-popover-foreground relative z-50 max-h-80 min-w-[var(--radix-select-trigger-width)] overflow-hidden rounded-lg border shadow-lg">
          <SelectPrimitive.Viewport className="p-1">
            {options.map((o) => (
              <SelectPrimitive.Item key={o.value} value={o.value} className="focus:bg-accent focus:text-accent-foreground relative flex w-full cursor-default items-center rounded-md py-1.5 pr-8 pl-2 text-sm outline-hidden select-none data-[disabled]:opacity-50">
                <SelectPrimitive.ItemText>{o.label}</SelectPrimitive.ItemText>
                <span className="absolute right-2 flex size-3.5 items-center justify-center">
                  <SelectPrimitive.ItemIndicator>
                    <CheckIcon className="size-4" />
                  </SelectPrimitive.ItemIndicator>
                </span>
              </SelectPrimitive.Item>
            ))}
          </SelectPrimitive.Viewport>
        </SelectPrimitive.Content>
      </SelectPrimitive.Portal>
    </SelectPrimitive.Root>
  )
}

// ---------------------------------------------------------------- scroll area
export function ScrollArea({ className, children, ...props }: React.ComponentProps<typeof ScrollAreaPrimitive.Root>) {
  return (
    <ScrollAreaPrimitive.Root className={cn('relative overflow-hidden', className)} {...props}>
      <ScrollAreaPrimitive.Viewport className="size-full rounded-[inherit]">{children}</ScrollAreaPrimitive.Viewport>
      <ScrollAreaPrimitive.Scrollbar orientation="vertical" className="flex w-2 touch-none p-px select-none">
        <ScrollAreaPrimitive.Thumb className="bg-border relative flex-1 rounded-full" />
      </ScrollAreaPrimitive.Scrollbar>
    </ScrollAreaPrimitive.Root>
  )
}
