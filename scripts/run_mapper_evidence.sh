#!/bin/sh
# Build all three mapper candidates, generate datasets, and compare them.
set -eu

if test "$#" -ne 2; then
    echo "usage: $0 TRUSTED_ORIGINAL_PICKLE OUTPUT_DIRECTORY" >&2
    exit 2
fi

original=$1
output=$2
test -f "$original" || {
    echo "original pickle does not exist: $original" >&2
    exit 2
}

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
repository=$(CDPATH= cd -- "$script_dir/.." && pwd -P)
original_dir=$(CDPATH= cd -- "$(dirname -- "$original")" && pwd -P)
original_name=$(basename -- "$original")
mkdir -p "$output"
output_dir=$(CDPATH= cd -- "$output" && pwd -P)

none_revision=463f9e94f5ea45e5be64bae06291423ead3b70f2
pre_revision=52383e2832a86feb452ddd80928bce69147f01c0
post_revision=15e71bf01be68d427ed9f37966b83efc1180a1d5
image_prefix=${RML_MAPPER_IMAGE_PREFIX:-radioml2016:mapper-evidence}
none_historical=${image_prefix}-none-historical
pre_historical=${image_prefix}-pre-historical
post_historical=${image_prefix}-post-historical
none_reproducible=${image_prefix}-none-reproducible
pre_reproducible=${image_prefix}-pre-reproducible
post_reproducible=${image_prefix}-post-reproducible

for path in no-normalization.dat pre-fix.dat post-fix.dat \
    snr-comparison.json images.json none-generation.log pre-generation.log \
    post-generation.log none-runtime.json pre-runtime.json post-runtime.json \
    none-runtime.log pre-runtime.log post-runtime.log; do
    test ! -e "$output_dir/$path" || {
        echo "refusing to overwrite: $output_dir/$path" >&2
        exit 2
    }
done

docker build --platform linux/amd64 -f "$repository/Dockerfile" \
    --build-arg "MAPPER_REV=$none_revision" \
    -t "$none_historical" "$repository"
docker build --platform linux/amd64 -f "$repository/Dockerfile" \
    --build-arg "MAPPER_REV=$pre_revision" \
    -t "$pre_historical" "$repository"
docker build --platform linux/amd64 -f "$repository/Dockerfile" \
    --build-arg "MAPPER_REV=$post_revision" \
    -t "$post_historical" "$repository"
docker build --platform linux/amd64 -f "$repository/Dockerfile.reproducible" \
    --build-arg "BASE_IMAGE=$none_historical" \
    -t "$none_reproducible" "$repository"
docker build --platform linux/amd64 -f "$repository/Dockerfile.reproducible" \
    --build-arg "BASE_IMAGE=$pre_historical" \
    -t "$pre_reproducible" "$repository"
docker build --platform linux/amd64 -f "$repository/Dockerfile.reproducible" \
    --build-arg "BASE_IMAGE=$post_historical" \
    -t "$post_reproducible" "$repository"

docker image inspect "$none_historical" "$pre_historical" "$post_historical" \
    "$none_reproducible" "$pre_reproducible" "$post_reproducible" \
    > "$output_dir/images.json"

docker run --rm --network none --user "$(id -u):$(id -g)" \
    -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 \
    -v "$repository:/work:ro" -v "$output_dir:/out" -w /work \
    "$none_historical" python2.7 scripts/check_historical_runtime.py \
    --mapper-amplitude 1 --pam4-amplitude 3 \
    --output /out/none-runtime.json \
    > "$output_dir/none-runtime.log" 2>&1
docker run --rm --network none --user "$(id -u):$(id -g)" \
    -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 \
    -v "$repository:/work:ro" -v "$output_dir:/out" -w /work \
    "$pre_historical" python2.7 scripts/check_historical_runtime.py \
    --mapper-amplitude 2 --pam4-amplitude 12 \
    --output /out/pre-runtime.json \
    > "$output_dir/pre-runtime.log" 2>&1
docker run --rm --network none --user "$(id -u):$(id -g)" \
    -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 \
    -v "$repository:/work:ro" -v "$output_dir:/out" -w /work \
    "$post_historical" python2.7 scripts/check_historical_runtime.py \
    --mapper-amplitude 1 --pam4-amplitude 1.5 \
    --output /out/post-runtime.json \
    > "$output_dir/post-runtime.log" 2>&1

for candidate in none pre post; do
    if test "$candidate" = none; then
        image=$none_reproducible
        destination=no-normalization.dat
    elif test "$candidate" = pre; then
        image=$pre_reproducible
        destination=pre-fix.dat
    else
        image=$post_reproducible
        destination=post-fix.dat
    fi
    docker run --rm --network none --user "$(id -u):$(id -g)" \
        -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 \
        -v "$repository:/work:ro" -v "$output_dir:/out" -w /work \
        "$image" python2.7 generate_RML2016.10a.py \
        --python-seed 201610 --numpy-seed 201610 \
        --channel-seed 0x1337 --channel-seed-policy advance \
        --scheduler sts --frames-per-key 1000 \
        --output "/out/$destination" \
        > "$output_dir/$candidate-generation.log" 2>&1
done

docker run --rm --network none --user "$(id -u):$(id -g)" \
    -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 \
    -v "$repository:/work:ro" -v "$original_dir:/input:ro" \
    -v "$output_dir:/out" -w /work "$post_reproducible" \
    python2.7 scripts/estimate_mapper_snr.py \
    "/input/$original_name" /out/pre-fix.dat /out/post-fix.dat \
    --no-normalization /out/no-normalization.dat \
    --expected-original-sha256 \
    b29ccc25b00d0718cd3b70ffa9158662ec83f6d9b63ffd845c7bcbe3b3096e8c \
    --output /out/snr-comparison.json

printf 'Mapper evidence written to %s\n' "$output_dir"
