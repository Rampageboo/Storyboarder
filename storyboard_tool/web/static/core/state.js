const state = {
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
  scene3dEditor: null,
  scene3dLoadedKey: null,
  timelineScrollLeft: 0,
  timelineScrollPendingRestore: false,
  refSegment: {
    segments: [],
    activeId: null,
  },
};

const dialogState = {
  resolve: null,
  browse: null,
  validate: null,
  hasInput: false,
  listItems: [],
};

const contextMenuState = {
  shotId: null,
};

const canvasColorState = {
  gray: 232,
  wired: false,
};
