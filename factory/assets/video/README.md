# Guide videos (factory only)

Every cafe package gets a guide video, copied from this folder by the build (spec 2.5, F7):

- `9t7.mp4`: the 9T7 Racing variant;
- `unbranded.mp4`: the unbranded variant, with every 9T7 Racing mark swapped for the Pitwall wordmark.

**LOCAL step (L3):** render both videos on the Windows PC and copy them here with exactly these names.
They are large, so `.gitignore` keeps them out of the repo (`factory/assets/video/*.mp4`); keep your own copy.

While the variant's video is missing, the factory refuses to build that variant's package with
"Guide video for this variant is missing." before it issues a licence or compiles anything.
In the package, the video is named "Pitwall guide video.mp4".
