self:
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.services.bible-typeset;
in
{
  options.services.bible-typeset = {
    enable = lib.mkEnableOption "the scripture typesetting web service";
    package = lib.mkOption {
      type = lib.types.package;
      default = self.packages.${pkgs.stdenv.hostPlatform.system}.default;
      description = "The bible-typeset package to run.";
    };
    dataDir = lib.mkOption {
      type = lib.types.path;
      description = "Directory containing the eBible *_usfx.zip files (read-only for the service).";
    };
    textsConfig = lib.mkOption {
      type = lib.types.nullOr lib.types.path;
      default = null;
      description = "Optional texts.toml replacing the bundled one.";
    };
    host = lib.mkOption {
      type = lib.types.str;
      default = "127.0.0.1";
    };
    port = lib.mkOption {
      type = lib.types.port;
      default = 8000;
    };
    openFirewall = lib.mkOption {
      type = lib.types.bool;
      default = false;
    };
  };

  config = lib.mkIf cfg.enable {
    systemd.services.bible-typeset = {
      wantedBy = [ "multi-user.target" ];
      after = [ "network.target" ];
      environment = {
        BIBLE_DATA_DIR = toString cfg.dataDir;
        BIBLE_HOST = cfg.host;
        BIBLE_PORT = toString cfg.port;
      }
      // lib.optionalAttrs (cfg.textsConfig != null) {
        BIBLE_TEXTS_CONFIG = toString cfg.textsConfig;
      };
      serviceConfig = {
        ExecStart = lib.getExe cfg.package;
        Restart = "on-failure";
        DynamicUser = true;
        # Typst runs as a child process on user-influenced input: keep the whole unit boxed in.
        ProtectSystem = "strict";
        ProtectHome = true;
        PrivateTmp = true;
        PrivateDevices = true;
        NoNewPrivileges = true;
        CapabilityBoundingSet = "";
        RestrictAddressFamilies = [
          "AF_INET"
          "AF_INET6"
          "AF_UNIX"
        ];
        SystemCallFilter = [
          "@system-service"
          "~@privileged"
        ];
        MemoryMax = "1G";
        ReadOnlyPaths = [ (toString cfg.dataDir) ];
      };
    };
    networking.firewall.allowedTCPPorts = lib.mkIf cfg.openFirewall [ cfg.port ];
  };
}
