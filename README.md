# RadioML 2016 Data Set

This repository is a fork of the RadioML dataset generation repository located at https://github.com/radioML/dataset. See the related paper[^4] for more details. It should be cloned recursively:

```shell-script
$ git clone --recursive https://github.com/mainland/radioml2016
```

## Docker container

The Dockerfile can be used to build a container with all software prerequisites needed to generate the dataset. It is meant to make it easy to mount the user's home directory in the docker container for seamless operation. The container cna be built as follows:

```shell-script
$ docker build . -f Dockerfile \
  --build-arg USERNAME=$USER \
  --build-arg USER_UID=$(id -u) \
  --build-arg USER_GID=$(id -g) \
  -t radioml2016
```

Once built, the following command will start the container and map the user (and the user's home directory) to the container:

```shell-script
$ docker run -it --rm \
  -u $(id -u):$(id -g) \
  -v "/etc/passwd:/etc/passwd:ro" \
  -v "/etc/group:/etc/group:ro" \
  -v /home/$USER:/home/$USER \
  -e DISPLAY \
  -v "/tmp/.X11-unix:/tmp/.X11-unix:rw" \
  radioml2016
```

Once in the container, the dataset can be generated with the command `python generate_RML2016.10a.py`.

## References

See also Chad Spooner's commentary on the dataset[^1][^2][^3].

[^1]: C. Spooner, “Machine Learning and Modulation Recognition: Comments on ‘Convolutional Radio Modulation Recognition Networks’ by T. O’Shea, J. Corgan, and T. Clancy,” Cyclostationary Signal Processing, Jan. 31, 2017. https://cyclostationary.blog/2017/01/31/machine-learning-and-modulation-recognition-comments-on-convolutional-radio-modulation-recognition-networks-by-t-oshea-j-corgan-and-t-clancy/ (accessed Jun. 16, 2022).
[^2]: C. Spooner, “More on DeepSig’s RML Data Sets,” Cyclostationary Signal Processing, Aug. 17, 2020. https://cyclostationary.blog/2020/08/17/more-on-deepsigs-rml-data-sets/ (accessed Jun. 16, 2022).
[^3]: C. Spooner, “All BPSK Signals,” Cyclostationary Signal Processing, Apr. 29, 2020. https://cyclostationary.blog/2020/04/29/all-bpsk-signals/ (accessed Jun. 16, 2022).
[^4]: T. J. O’Shea, J. Corgan, and T. C. Clancy, “Convolutional radio modulation recognition networks,” in International Conference on Engineering Applications of Neural Networks, 2016, pp. 213–226. doi: 10.1007/978-3-319-44188-7_16.
