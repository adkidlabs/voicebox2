import { Mic, Pause, Play, Upload } from 'lucide-react';
import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { FormControl, FormItem, FormMessage } from '@/components/ui/form';

interface AudioSampleUploadProps {
  file: File | null | undefined;
  onFileChange: (file: File | undefined) => void;
  onTranscribe: () => void;
  onPlayPause: () => void;
  isPlaying: boolean;
  isValidating?: boolean;
  isTranscribing?: boolean;
  isDisabled?: boolean;
  fieldName: string;
  /** W2: when true, extra dropped/chosen files go to onExtraFiles as clone samples. */
  allowMultiple?: boolean;
  onExtraFiles?: (files: File[]) => void;
}

export function AudioSampleUpload({
  file,
  onFileChange,
  onTranscribe,
  onPlayPause,
  isPlaying,
  isValidating = false,
  isTranscribing = false,
  isDisabled = false,
  fieldName,
  allowMultiple = false,
  onExtraFiles,
}: AudioSampleUploadProps) {
  const { t } = useTranslation();
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFiles = (files: File[]) => {
    const audioFiles = files.filter((f) => f.type.startsWith('audio/') || /\.(wav|mp3|m4a|ogg|flac|aac|webm|opus)$/i.test(f.name));
    if (audioFiles.length === 0) return;
    if (!file) {
      onFileChange(audioFiles[0]);
      if (audioFiles.length > 1) onExtraFiles?.(audioFiles.slice(1));
    } else if (allowMultiple) {
      onExtraFiles?.(audioFiles);
    } else {
      onFileChange(audioFiles[0]);
    }
  };

  return (
    <FormItem>
      <FormControl>
        <div className="flex flex-col gap-2">
          <input
            type="file"
            accept="audio/*"
            multiple={allowMultiple}
            name={fieldName}
            ref={fileInputRef}
            onChange={(e) => {
              const chosen = Array.from(e.target.files ?? []);
              if (chosen.length > 0) {
                handleFiles(chosen);
              } else {
                onFileChange(undefined);
              }
            }}
            className="hidden"
          />
          <div
            role="button"
            tabIndex={0}
            onDragOver={(e) => {
              e.preventDefault();
              setIsDragging(true);
            }}
            onDragLeave={(e) => {
              e.preventDefault();
              setIsDragging(false);
            }}
            onDrop={(e) => {
              e.preventDefault();
              setIsDragging(false);
              handleFiles(Array.from(e.dataTransfer.files ?? []));
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                fileInputRef.current?.click();
              }
            }}
            className={`flex flex-col items-center justify-center gap-4 p-4 border-2 rounded-lg transition-colors min-h-[180px] ${
              file
                ? 'border-primary bg-primary/5'
                : isDragging
                  ? 'border-primary bg-primary/5'
                  : 'border-dashed border-muted-foreground/25 hover:border-muted-foreground/50'
            }`}
          >
            {!file ? (
              <>
                <Button
                  type="button"
                  size="lg"
                  onClick={() => fileInputRef.current?.click()}
                  className="flex items-center gap-2"
                >
                  <Upload className="h-5 w-5" />
                  {t('audioSample.chooseFile')}
                </Button>
                <p className="text-sm text-muted-foreground text-center">
                  {t('audioSample.uploadHint')}
                </p>
              </>
            ) : (
              <>
                <div className="flex items-center gap-2">
                  <Upload className="h-5 w-5 text-primary" />
                  <span className="font-medium">{t('audioSample.fileUploaded')}</span>
                </div>
                <p className="text-sm text-muted-foreground text-center">
                  {t('audioSample.fileLabel', { name: file.name })}
                </p>
                <div className="flex gap-2">
                  <Button
                    type="button"
                    size="icon"
                    variant="outline"
                    onClick={onPlayPause}
                    disabled={isValidating}
                    aria-label={isPlaying ? t('audioSample.pause') : t('audioSample.play')}
                  >
                    {isPlaying ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={onTranscribe}
                    disabled={isTranscribing || isValidating || isDisabled}
                    className="flex items-center gap-2"
                  >
                    <Mic className="h-4 w-4" />
                    {isTranscribing ? t('audioSample.transcribing') : t('audioSample.transcribe')}
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => {
                      onFileChange(undefined);
                      if (fileInputRef.current) {
                        fileInputRef.current.value = '';
                      }
                    }}
                  >
                    {t('audioSample.remove')}
                  </Button>
                </div>
              </>
            )}
          </div>
        </div>
      </FormControl>
      <FormMessage />
    </FormItem>
  );
}
