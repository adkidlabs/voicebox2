import { AlertTriangle, BadgeCheck, OctagonAlert } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { SampleQualityResult } from '@/lib/api/types';
import { cn } from '@/lib/utils/cn';

interface ConfidenceBadgeProps {
  result: SampleQualityResult | null;
  pending?: boolean;
  className?: string;
}

/**
 * Clone-sample confidence badge (W2). Pure-warning: green/amber/red reflect
 * the pre-flight score, and warning texts render underneath. Never blocks.
 */
export function ConfidenceBadge({ result, pending, className }: ConfidenceBadgeProps) {
  const { t } = useTranslation();

  if (pending) {
    return (
      <div className={cn('text-xs text-muted-foreground', className)}>
        {t('profileForm.quality.checking')}
      </div>
    );
  }

  if (!result) return null;

  const hasError = result.warnings.some((w) => w.severity === 'error');
  const tone = hasError || result.score < 50 ? 'bad' : result.score < 76 ? 'warn' : 'good';

  const Icon = tone === 'good' ? BadgeCheck : tone === 'warn' ? AlertTriangle : OctagonAlert;

  return (
    <div className={cn('space-y-1', className)}>
      <div
        className={cn(
          'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium',
          tone === 'good' && 'border-emerald-500/40 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400',
          tone === 'warn' && 'border-amber-500/40 bg-amber-500/10 text-amber-600 dark:text-amber-400',
          tone === 'bad' && 'border-red-500/40 bg-red-500/10 text-red-600 dark:text-red-400',
        )}
      >
        <Icon className="h-3.5 w-3.5" />
        <span>{t('profileForm.quality.score', { score: result.score })}</span>
      </div>
      {result.warnings.length > 0 && (
        <ul className="space-y-0.5 text-xs text-muted-foreground">
          {result.warnings.map((w) => (
            <li key={w.code} className="flex items-start gap-1">
              <span aria-hidden>•</span>
              <span>{w.message}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
