/* Fault-profile <option>s and the plain-language note shown under a fault-profile picker
   (evaluation runs and Adversarial Lab custom attacks). */
import { Bug } from 'lucide-react'

import { FAULT_PROFILE_INFO, faultTitle } from '@/components/insights/fault-profiles'

export function FaultProfileOptions({ profiles, noneLabel = 'None — use the AI answer as it is' }: { profiles: Record<string, string>; noneLabel?: string }) {
  return (
    <>
      <option value="">{noneLabel}</option>
      {Object.keys(profiles).map((k) => (
        <option key={k} value={k}>
          {faultTitle(k)} ({k})
        </option>
      ))}
    </>
  )
}

export function FaultProfileNote({ profile, profiles }: { profile: string; profiles: Record<string, string> }) {
  if (!profile) return null
  const info = FAULT_PROFILE_INFO[profile]
  return (
    <div className="border-warning/35 bg-warning/8 flex gap-2.5 rounded-lg border px-3 py-2 text-xs" role="note">
      <Bug className="mt-0.5 size-3.5 shrink-0 text-[oklch(0.5_0.13_60)] dark:text-warning" aria-hidden />
      <div className="space-y-0.5">
        <p>
          <span className="font-semibold">{info?.title ?? profile}:</span> {info?.plain ?? profiles[profile]}
        </p>
        {info ? (
          <p className="text-muted-foreground">
            How it is caught: {info.caughtBy}
            {info.checks.length ? ` (${info.checks.join(', ')})` : ''}
          </p>
        ) : null}
      </div>
    </div>
  )
}
