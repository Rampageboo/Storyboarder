import type { ProjectPayload } from './types/project'

export function canConvertProjectToLayout2(project: ProjectPayload | null): boolean {
  return project?.can_convert_to_layout2 === true
}
