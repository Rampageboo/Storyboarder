import {
  TriangleFanDrawMode,
  TriangleStripDrawMode,
  TrianglesDrawMode,
} from "../three/three.module.js";

/**
 * Minimal BufferGeometryUtils for GLTFLoader (Three.js r169 compatible).
 */
function toTrianglesDrawMode(geometry, drawMode) {
  if (drawMode === TrianglesDrawMode) {
    return geometry;
  }

  if (drawMode === TriangleFanDrawMode || drawMode === TriangleStripDrawMode) {
    let index = geometry.getIndex();

    if (index === null) {
      const indices = [];
      const position = geometry.getAttribute("position");
      if (position !== undefined) {
        for (let i = 0; i < position.count; i += 1) {
          indices.push(i);
        }
        geometry.setIndex(indices);
        index = geometry.getIndex();
      } else {
        console.error(
          "THREE.BufferGeometryUtils.toTrianglesDrawMode(): Undefined position attribute. Processing not possible."
        );
        return geometry;
      }
    }

    const numberOfTriangles = index.count - 2;
    const newIndices = [];

    if (drawMode === TriangleFanDrawMode) {
      for (let i = 1; i <= numberOfTriangles; i += 1) {
        newIndices.push(index.getX(0));
        newIndices.push(index.getX(i));
        newIndices.push(index.getX(i + 1));
      }
    } else {
      for (let i = 0; i < numberOfTriangles; i += 1) {
        if (i % 2 === 0) {
          newIndices.push(index.getX(i));
          newIndices.push(index.getX(i + 1));
          newIndices.push(index.getX(i + 2));
        } else {
          newIndices.push(index.getX(i + 2));
          newIndices.push(index.getX(i + 1));
          newIndices.push(index.getX(i));
        }
      }
    }

    const newGeometry = geometry.clone();
    newGeometry.setIndex(newIndices);
    newGeometry.clearGroups();
    return newGeometry;
  }

  console.error("THREE.BufferGeometryUtils.toTrianglesDrawMode(): Unknown draw mode:", drawMode);
  return geometry;
}

export { toTrianglesDrawMode };
