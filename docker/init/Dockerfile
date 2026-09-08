# La imagen oficial de Garage es FROM scratch: no trae shell, asi que no se
# puede ejecutar un script de inicializacion dentro de ella. El binario de
# Garage es estatico (musl), de modo que basta copiarlo sobre alpine.
FROM dxflrs/garage:v1.0.1 AS garage

FROM alpine:3.20
COPY --from=garage /garage /usr/local/bin/garage
COPY garage-init.sh /usr/local/bin/garage-init.sh
RUN chmod +x /usr/local/bin/garage-init.sh
ENTRYPOINT ["/usr/local/bin/garage-init.sh"]
