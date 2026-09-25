/* Roles x permissions grid (server-side RBAC). Used by the Adversarial Lab (/lab/access-matrix)
   and the Administration roles panel (/roles). */
import { Check, X } from 'lucide-react'
import * as React from 'react'

import { humanize, PERMISSION_LABELS, permissionGroup } from '@/components/insights/format'
import { cn } from '@/lib/utils'

export function AccessMatrixTable({ roles, permissions, granted, currentRole, caption }: {
  roles: { code: string; name: string }[]
  permissions: string[]
  granted: (role: string, permission: string) => boolean
  /** Highlights the signed-in user's column. */
  currentRole?: string
  caption?: string
}) {
  const groups = React.useMemo(() => {
    const map = new Map<string, string[]>()
    for (const p of [...permissions].sort()) {
      const g = permissionGroup(p)
      map.set(g, [...(map.get(g) ?? []), p])
    }
    return [...map.entries()]
  }, [permissions])
  const counts = roles.map((r) => permissions.filter((p) => granted(r.code, p)).length)

  return (
    <div className="relative w-full overflow-x-auto rounded-lg border scrollbar-thin">
      <table className="w-full min-w-[44rem] text-sm">
        {caption ? <caption className="sr-only">{caption}</caption> : null}
        <thead className="bg-muted/40">
          <tr className="border-b">
            <th scope="col" className="bg-muted/95 text-muted-foreground sticky left-0 z-10 h-11 min-w-[15rem] px-3 text-left text-xs font-semibold uppercase tracking-wide backdrop-blur">
              Permission
            </th>
            {roles.map((r, i) => (
              <th
                key={r.code}
                scope="col"
                className={cn('h-11 px-2 text-center text-xs font-semibold whitespace-nowrap', r.code === currentRole ? 'bg-primary/10 text-primary' : 'text-muted-foreground')}
              >
                <div>{r.name}</div>
                <div className="text-[10px] font-normal tabular-nums opacity-80">
                  {counts[i]} of {permissions.length}
                  {r.code === currentRole ? ' · you' : ''}
                </div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {groups.map(([group, perms]) => (
            <React.Fragment key={group}>
              <tr className="bg-muted/20 border-b">
                <th scope="colgroup" colSpan={roles.length + 1} className="text-muted-foreground sticky left-0 px-3 py-1.5 text-left text-[11px] font-semibold uppercase tracking-wide">
                  {humanize(group)}
                </th>
              </tr>
              {perms.map((p) => (
                <tr key={p} className="hover:bg-muted/30 border-b last:border-0">
                  <th scope="row" className="bg-card sticky left-0 z-[1] px-3 py-2 text-left font-normal">
                    <div className="font-mono text-xs font-medium">{p}</div>
                    {PERMISSION_LABELS[p] ? <div className="text-muted-foreground text-xs">{PERMISSION_LABELS[p]}</div> : null}
                  </th>
                  {roles.map((r) => {
                    const ok = granted(r.code, p)
                    return (
                      <td key={r.code} className={cn('px-2 py-2 text-center', r.code === currentRole && 'bg-primary/5')}>
                        {ok ? (
                          <span className="bg-success/12 text-success inline-flex size-6 items-center justify-center rounded-full">
                            <Check className="size-3.5" aria-hidden />
                            <span className="sr-only">{r.name} has {p}</span>
                          </span>
                        ) : (
                          <span className="text-muted-foreground/45 inline-flex size-6 items-center justify-center">
                            <X className="size-3.5" aria-hidden />
                            <span className="sr-only">{r.name} does not have {p}</span>
                          </span>
                        )}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </React.Fragment>
          ))}
        </tbody>
      </table>
    </div>
  )
}
