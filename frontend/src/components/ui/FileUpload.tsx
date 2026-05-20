"use client";

/**
 * FileUpload — extracted, reusable upload zone component.
 *
 * Wraps FileDropzone with consistent layout for 3D + 2D file pairs.
 * Pure UI: no API calls inside. All state managed by parent.
 */

import { FileDropzone } from "@/components/upload/file-dropzone";

interface FileUploadProps {
  file3d: File | null;
  file2d: File | null;
  onFile3dChange: (f: File | null) => void;
  onFile2dChange: (f: File | null) => void;
  error3d?: string;
  error2d?: string;
  onReject3d?: (reason: string) => void;
  onReject2d?: (reason: string) => void;
}

export function FileUpload({
  file3d, file2d,
  onFile3dChange, onFile2dChange,
  error3d, error2d,
  onReject3d, onReject2d,
}: FileUploadProps) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      <FileDropzone
        label="3D CAD File"
        description="STEP / STP — required"
        accept={{
          "application/step": [".stp", ".step"],
          "application/octet-stream": [".stp", ".step"],
        }}
        file={file3d}
        onFileSelect={onFile3dChange}
        icon="3d"
        required
        error={error3d}
        onReject={onReject3d}
      />
      <FileDropzone
        label="2D Engineering Drawing"
        description="PDF, PNG, JPG, or TIFF — required"
        accept={{
          "application/pdf": [".pdf"],
          "image/png": [".png"],
          "image/jpeg": [".jpg", ".jpeg"],
          "image/tiff": [".tiff"],
        }}
        file={file2d}
        onFileSelect={onFile2dChange}
        icon="2d"
        required
        error={error2d}
        onReject={onReject2d}
      />
    </div>
  );
}
