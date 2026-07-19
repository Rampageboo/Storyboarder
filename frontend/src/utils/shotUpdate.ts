import type { Shot, ShotUpdate } from '../types'

export function shotToUpdate(shot: Shot): ShotUpdate {
  return {
    title: shot.title,
    scene: shot.scene,
    scene_id: shot.scene_id,
    sequence: shot.sequence,
    description: shot.description,
    action_note: shot.action_note,
    camera_note: shot.camera_note,
    character_note: shot.character_note,
    dialogue: shot.dialogue,
    lighting_note: shot.lighting_note,
    transition_note: shot.transition_note,
    duration_seconds: shot.duration_seconds,
    camera_data: shot.camera_data,
    tags: shot.tags,
    status: shot.status,
    shot_design: shot.shot_design,
    prompt_config: shot.prompt_config,
    continuity: shot.continuity,
  }
}
