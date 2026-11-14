# Build context je HW3/mcp-dotnet/.
#   docker build -f HW3/mcp-dotnet/Dockerfile HW3/mcp-dotnet
#
# Image nepotřebuje HW1 ani databázi — na data sahá přes HTTP API z HW2.
# Base image digestem; aktualizace = nový digest v commitu.
FROM mcr.microsoft.com/dotnet/sdk:10.0@sha256:0d99ebf1ccad15037b5c98c9fe8979d6b8dbac23812feae2277a0b277b5c5ffa AS build
WORKDIR /src
# nuget.config pouští jen nuget.org, packages.lock.json zamyká graf závislostí.
COPY nuget.config ./
COPY TimeAgent.Mcp/TimeAgent.Mcp.csproj TimeAgent.Mcp/packages.lock.json TimeAgent.Mcp/
RUN dotnet restore TimeAgent.Mcp/TimeAgent.Mcp.csproj --locked-mode
COPY TimeAgent.Mcp/ TimeAgent.Mcp/
RUN dotnet publish TimeAgent.Mcp/TimeAgent.Mcp.csproj -c Release -o /app -p:RestoreLockedMode=true

FROM mcr.microsoft.com/dotnet/aspnet:11.0@sha256:bc0d6653979efba491ab3d6f589d691f96c309c3c3ef81325efa6978e7b7f242
WORKDIR /app
COPY --from=build /app .
ENV ASPNETCORE_URLS=http://0.0.0.0:8000
EXPOSE 8000
ENTRYPOINT ["dotnet", "TimeAgent.Mcp.dll"]
