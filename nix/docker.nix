{
  dockerTools,
  app,
}:

dockerTools.buildLayeredImage {
  name = "manuscript-discovery";
  tag = "latest";

  contents = [ app ];
  extraCommands = "mkdir -p tmp && chmod 1777 tmp";

  config = {
    Entrypoint = [ "${app}/bin/manuscript-discovery" ];
    Cmd = [ "serve" ]; # or: ingest /sources
    User = "65534:65534";
    ExposedPorts."8000/tcp" = { };
    Volumes."/data" = { };

    Env = [
      "MANUSCRIPT_DB_PATH=/data/library.sqlite"
      "MANUSCRIPT_HOST=0.0.0.0"
      "MANUSCRIPT_PORT=8000"
    ];
  };
}
