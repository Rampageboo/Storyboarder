export type ComicMode = 'page' | 'spread' | 'scroll'
export interface ComicChapter { id: string; title: string; prompt: string }
export interface ComicPanel {
  id: string; shot_id: string; x: number; y: number; width: number; height: number
  fit: 'contain' | 'cover'; border: number
  points?: [number, number][] | null; locked?: boolean
  image_scale?: number; image_x?: number; image_y?: number
}
export interface ComicLettering {
  id: string; kind: 'speech' | 'caption' | 'text'; text: string
  x: number; y: number; width: number; height: number; font_size: number
  vertical: boolean; color: string; fill: string; border: number
  tail: number
}
export interface ComicPage {
  id: string; chapter_id: string; title: string; mode: ComicMode
  width: number; height: number; gutter: number; prompt: string; panels: ComicPanel[]
  lettering?: ComicLettering[]; background?: string; safe_margin?: number
}
export interface ComicDocument {
  version: 1; revision: number; reading_direction: 'ltr' | 'rtl'; style_prompt: string
  chapters: ComicChapter[]; pages: ComicPage[]
}
export function emptyComic(): ComicDocument {
  return { version: 1, revision: 0, reading_direction: 'ltr', style_prompt: '', chapters: [], pages: [] }
}
