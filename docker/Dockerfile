#Build image
FROM python:3.13-trixie AS builder

RUN apt update && \
    apt install -y gcc python3-pip python3.13-venv git && \
    curl https://sh.rustup.rs -sSf | sh -s -- -y

RUN python3 -m venv /app/venv
ENV PATH="/app/venv/bin:/root/.cargo/bin:${PATH}"

WORKDIR /ogre
RUN git clone https://github.com/ANSSI-FR/dfir-ogre-plugin-windows.git
RUN git clone https://github.com/ANSSI-FR/dfir-ogre.git

RUN umask 022 && \
    pip install /ogre/dfir-ogre

#Final image using a slim debian
FROM python:3.13-slim-trixie

COPY --chmod=755 dfir-ogre-plugin-windows/configuration /configuration
COPY --chmod=755 --from=builder /app/venv /app/venv

ENV PATH="/app/bin:$PATH"

ENTRYPOINT ["/app/venv/bin/dfir-ogre"]
