#!/usr/bin/env bash
set -euo pipefail

suite=${1:?usage: validate.sh fast|full IMAGE OUTPUT}
image=${2:?missing image}
output=$(realpath -m "${3:?missing output directory}")
case "$suite" in
  fast|full) ;;
  *) echo "Unknown validation suite: $suite" >&2; exit 2 ;;
esac
repo=$(git rev-parse --show-toplevel)
cd "$repo"
if [[ -e "$output/data" ]]; then
  echo "Refusing to reuse validation data directory: $output/data" >&2
  exit 2
fi
mkdir -p "$output/reports/generated" "$output/data"

# Retain reports and actual hashes even if a check fails.
collect_reports() {
  status=$?
  trap - EXIT
  set +e
  (
    cd "$output/data" || exit
    find . -type f \
      \( -name '*.json' -o -name '*.log' \) \
      -exec cp --parents --target-directory="$output/reports/generated" {} + \
      || exit 1
    find . -type f \
      \( -name '*.dat' -o -name '*.h5' \) -print0 \
      | sort -z | xargs -0 -r sha256sum
  ) > "$output/reports/generated-SHA256SUMS"
  collection_status=$?
  if [[ "$status" == 0 ]]; then
    status=$collection_status
  fi
  echo "$status" > "$output/reports/exit-code.txt"
  exit "$status"
}
trap collect_reports EXIT

git rev-parse HEAD > "$output/reports/source-commit.txt"
git submodule status --recursive > "$output/reports/submodules.txt"
git status --porcelain=v1 > "$output/reports/source-status.txt"
{
  printf 'suite=%s\nimage=%s\n' "$suite" "$image"
  uname -a
  lscpu
} > "$output/reports/execution.txt"
docker version > "$output/reports/docker-version.txt"
docker image inspect "$image" > "$output/reports/image.json"
docker run --rm --network none --user 0:0 "$image" \
  tar -C /opt/replay-provenance -cf - . \
  > "$output/reports/runtime-provenance.tar"

container=(docker run --rm --network none --user "$(id -u):$(id -g)"
  -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1
  -v "$repo:/work:ro" -v "$output:/out" -w /work "$image")
run_check() {
  local name=$1
  shift
  "${container[@]}" "$@" 2>&1 | tee "$output/reports/$name.log"
}

run_check fast python2.7 -m pytest -q -m 'not slow' tests \
  --junitxml=/out/reports/pytest.xml --basetemp=/out/data/pytest
if [[ "$suite" == full ]]; then
  status=0
  run_check datasets python2.7 tests/check_datasets.py \
    --output /out/data/datasets || status=$?
  run_check matrix python2.7 tests/check_reproducibility.py \
    --output /out/data/matrix || status=$?
  exit "$status"
fi
