import { CircleStop, Play } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { cn } from '@/lib/utils/cn';

interface AudioPreviewButtonProps {
  src: string;
  label?: string;
  className?: string;
}

export function AudioPreviewButton({ src, label, className }: AudioPreviewButtonProps) {
  const [isPlaying, setIsPlaying] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const toggle = (e: React.MouseEvent) => {
    e.stopPropagation();
    e.preventDefault();

    if (audioRef.current) {
      if (isPlaying) {
        audioRef.current.pause();
        setIsPlaying(false);
      } else {
        audioRef.current.play().catch(() => setIsPlaying(false));
        setIsPlaying(true);
      }
      return;
    }

    const audio = new Audio(src);
    audio.addEventListener('ended', () => setIsPlaying(false));
    audio.addEventListener('error', () => setIsPlaying(false));
    audioRef.current = audio;
    audio.play().catch(() => setIsPlaying(false));
    setIsPlaying(true);
  };

  useEffect(() => {
    return () => {
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current = null;
      }
    };
  }, []);

  return (
    <button
      type="button"
      aria-label={label ?? 'Preview voice'}
      title={label ?? 'Preview voice'}
      onClick={toggle}
      className={cn(
        'inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-border',
        'text-muted-foreground transition-colors hover:bg-muted hover:text-foreground',
        isPlaying && 'border-accent bg-accent/10 text-accent-foreground',
        className,
      )}
    >
      {isPlaying ? <CircleStop className="h-3 w-3" /> : <Play className="h-3 w-3 translate-x-px" />}
    </button>
  );
}
