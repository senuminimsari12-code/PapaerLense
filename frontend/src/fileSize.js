// Turn a number of bytes into something a person can read.
//
// 1024 is the step between units: 1024 bytes = 1 KB, 1024 KB = 1 MB.
//
//   formatFileSize(900)      -> "900 bytes"
//   formatFileSize(2048)     -> "2.0 KB"
//   formatFileSize(3500000)  -> "3.3 MB"
//
// toFixed(1) keeps exactly one decimal place, so sizes line up tidily in the UI.
export function formatFileSize(bytes) {
  if (bytes < 1024) {
    return `${bytes} bytes`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
