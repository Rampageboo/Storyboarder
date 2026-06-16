export const state = {
  project: null,
  selectedShotId: null,
  saveTimer: null,
  missingFiles: [],
  statusFilter: "",
  revisionOnly: false,
  animaticTimer: null,
  animaticStartedAt: 0,
  animaticOffset: 0,
  timelineCursor: 0,
  annotations: [],
  annotationTool: "select",
  annotationsVisible: true,
  drawing: null,
  syncPollTimer: null,
  liveBridgeTimer: null,
  bridgeStatusTimer: null,
  isSyncing: false,
  openInPsShotIds: [],
  scene3dEditor: null,
  scene3dLoadedKey: null,
  timelineScrollLeft: 0,
  timelineScrollPendingRestore: false,
  refSegment: {
    segments: [],
    activeId: null,
    // Id of a transient multi-board selection awaiting a reference assignment.
    pendingAssignId: null,
  },
};

export const dialogState = {
  resolve: null,
  browse: null,
  validate: null,
  hasInput: false,
  listItems: [],
};

export const contextMenuState = {
  shotId: null,
};

export const canvasColorState = {
  gray: 232,
  wired: false,
};
