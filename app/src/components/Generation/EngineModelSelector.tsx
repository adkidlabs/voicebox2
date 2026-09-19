import { useEffect, useMemo } from 'react';
import type { UseFormReturn } from 'react-hook-form';
import { FormControl } from '@/components/ui/form';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import type { VoiceProfileResponse } from '@/lib/api/types';
import { getLanguageOptionsForEngine } from '@/lib/constants/languages';
import type { GenerationFormValues } from '@/lib/hooks/useGenerationForm';
import { useEngines, type EngineInfo } from '@/lib/hooks/useEngines';

export interface EngineOption {
  value: string;
  label: string;
  engine: string;
}

/**
 * Static fallback options used when `GET /engines` is unreachable.
 * Mirrors the backend registry (TADA removed in W1).
 */
const FALLBACK_OPTIONS: EngineOption[] = [
  { value: 'qwen:1.7B', label: 'Qwen3-TTS 1.7B', engine: 'qwen' },
  { value: 'qwen:0.6B', label: 'Qwen3-TTS 0.6B', engine: 'qwen' },
  { value: 'qwen_custom_voice:1.7B', label: 'Qwen CustomVoice 1.7B', engine: 'qwen_custom_voice' },
  { value: 'qwen_custom_voice:0.6B', label: 'Qwen CustomVoice 0.6B', engine: 'qwen_custom_voice' },
  { value: 'luxtts', label: 'LuxTTS', engine: 'luxtts' },
  { value: 'chatterbox', label: 'Chatterbox', engine: 'chatterbox' },
  { value: 'chatterbox_turbo', label: 'Chatterbox Turbo', engine: 'chatterbox_turbo' },
  { value: 'kokoro', label: 'Kokoro 82M', engine: 'kokoro' },
  { value: 'moss_tts_nano', label: 'MOSS-TTS-Nano', engine: 'moss_tts_nano' },
  { value: 'auk', label: 'AuK-Flash (Experimental)', engine: 'auk' },
];

const FALLBACK_DESCRIPTIONS: Record<string, string> = {
  qwen: 'Multi-language, two sizes',
  qwen_custom_voice: '9 preset voices, instruct control',
  luxtts: 'Fast, English-focused',
  chatterbox: '23 languages, incl. Hebrew',
  chatterbox_turbo: 'English, [laugh] [cough] tags',
  kokoro: '82M params, CPU realtime, 8 langs',
  moss_tts_nano: '0.1B, CPU realtime, 48kHz, zero-shot clone',
  auk: 'Experimental 1.5B, zh/en only, ~14GB',
};

/** Engines that only support English and should force language to 'en' on select. */
const ENGLISH_ONLY_ENGINES = new Set(['luxtts', 'chatterbox_turbo']);

/** Fallback cloning set when the registry is unreachable. */
const FALLBACK_CLONING_ENGINES = new Set([
  'qwen',
  'luxtts',
  'chatterbox',
  'chatterbox_turbo',
  'moss_tts_nano',
  'auk',
]);

function optionsFromRegistry(engines: EngineInfo[]): EngineOption[] {
  const options: EngineOption[] = [];
  for (const info of engines) {
    if (!info.models.length) {
      options.push({ value: info.engine, label: info.display_name, engine: info.engine });
      continue;
    }
    const sized = info.models.length > 1;
    for (const variant of info.models) {
      options.push({
        value: sized ? `${info.engine}:${variant.model_size}` : info.engine,
        label: variant.display_name,
        engine: info.engine,
      });
    }
  }
  return options.length ? options : FALLBACK_OPTIONS;
}

function getAvailableOptions(
  allOptions: EngineOption[],
  selectedProfile?: VoiceProfileResponse | null,
  cloningEngines?: Set<string>,
) {
  if (!selectedProfile) return allOptions;
  return allOptions.filter((opt) =>
    isProfileCompatibleWithEngine(selectedProfile, opt.engine, cloningEngines),
  );
}

function getSelectValue(engine: string, modelSize?: string): string {
  if (engine === 'qwen') return `qwen:${modelSize || '1.7B'}`;
  if (engine === 'qwen_custom_voice') return `qwen_custom_voice:${modelSize || '1.7B'}`;
  return engine;
}

export function applyEngineSelection(form: UseFormReturn<GenerationFormValues>, value: string) {
  if (value.startsWith('qwen_custom_voice:')) {
    const [, modelSize] = value.split(':');
    form.setValue('engine', 'qwen_custom_voice');
    form.setValue('modelSize', modelSize as '1.7B' | '0.6B');
    const currentLang = form.getValues('language');
    const available = getLanguageOptionsForEngine('qwen_custom_voice');
    if (!available.some((l) => l.value === currentLang)) {
      form.setValue('language', available[0]?.value ?? 'en');
    }
  } else if (value.startsWith('qwen:')) {
    const [, modelSize] = value.split(':');
    form.setValue('engine', 'qwen');
    form.setValue('modelSize', modelSize as '1.7B' | '0.6B');
    // Validate language is supported by Qwen
    const currentLang = form.getValues('language');
    const available = getLanguageOptionsForEngine('qwen');
    if (!available.some((l) => l.value === currentLang)) {
      form.setValue('language', available[0]?.value ?? 'en');
    }
  } else {
    form.setValue('engine', value as GenerationFormValues['engine']);
    form.setValue('modelSize', undefined as unknown as '1.7B' | '0.6B');
    if (ENGLISH_ONLY_ENGINES.has(value)) {
      form.setValue('language', 'en');
    } else {
      // If current language isn't supported by the new engine, reset to first available
      const currentLang = form.getValues('language');
      const available = getLanguageOptionsForEngine(value);
      if (!available.some((l) => l.value === currentLang)) {
        form.setValue('language', available[0]?.value ?? 'en');
      }
    }
  }
}

interface EngineModelSelectorProps {
  form: UseFormReturn<GenerationFormValues>;
  compact?: boolean;
  selectedProfile?: VoiceProfileResponse | null;
}

export function EngineModelSelector({ form, compact, selectedProfile }: EngineModelSelectorProps) {
  const { data: registryEngines } = useEngines();
  const allOptions = useMemo(
    () => (registryEngines ? optionsFromRegistry(registryEngines) : FALLBACK_OPTIONS),
    [registryEngines],
  );
  const cloningEngines = useMemo(() => {
    if (!registryEngines) return FALLBACK_CLONING_ENGINES;
    return new Set(
      registryEngines.filter((e) => e.supports_cloning).map((e) => e.engine),
    );
  }, [registryEngines]);

  const engine = form.watch('engine') || 'qwen';
  const modelSize = form.watch('modelSize');
  const selectValue = getSelectValue(engine, modelSize);
  const availableOptions = getAvailableOptions(allOptions, selectedProfile, cloningEngines);

  const currentEngineAvailable = availableOptions.some((opt) => opt.value === selectValue);

  useEffect(() => {
    if (!currentEngineAvailable && availableOptions.length > 0) {
      applyEngineSelection(form, availableOptions[0].value);
    }
  }, [availableOptions, currentEngineAvailable, form]);

  const itemClass = compact ? 'text-xs text-muted-foreground' : undefined;
  const triggerClass = compact
    ? 'h-8 text-xs bg-card border-border rounded-full hover:bg-background/50 transition-all'
    : undefined;

  return (
    <Select value={selectValue} onValueChange={(v) => applyEngineSelection(form, v)}>
      <FormControl>
        <SelectTrigger className={triggerClass}>
          <SelectValue />
        </SelectTrigger>
      </FormControl>
      <SelectContent side={compact ? 'top' : undefined}>
        {availableOptions.map((opt) => (
          <SelectItem key={opt.value} value={opt.value} className={itemClass}>
            {opt.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

/** Returns a human-readable description for the currently selected engine. */
export function getEngineDescription(engine: string, registryEngines?: EngineInfo[]): string {
  const fromRegistry = registryEngines?.find((e) => e.engine === engine)?.description;
  return fromRegistry ?? FALLBACK_DESCRIPTIONS[engine] ?? '';
}

/**
 * Check if a profile is compatible with the currently selected engine.
 * Useful for UI hints.
 */
export function isProfileCompatibleWithEngine(
  profile: VoiceProfileResponse,
  engine: string,
  cloningEngines: Set<string> = FALLBACK_CLONING_ENGINES,
): boolean {
  const voiceType = profile.voice_type || 'cloned';
  if (voiceType === 'preset') return profile.preset_engine === engine;
  if (voiceType === 'cloned') return cloningEngines.has(engine);
  return true; // designed — future
}
