# Build context je HW3/mcp-dotnet/.
#   docker build -f HW3/mcp-dotnet/Dockerfile HW3/mcp-dotnet
#
# Image nepotřebuje HW1 ani databázi — na data sahá přes HTTP API z HW2.
FROM mcr.microsoft.com/dotnet/sdk:10.0 AS build
WORKDIR /src
COPY TimeAgent.Mcp/TimeAgent.Mcp.csproj TimeAgent.Mcp/
RUN dotnet restore TimeAgent.Mcp/TimeAgent.Mcp.csproj
COPY TimeAgent.Mcp/ TimeAgent.Mcp/
RUN dotnet publish TimeAgent.Mcp/TimeAgent.Mcp.csproj -c Release -o /app

FROM mcr.microsoft.com/dotnet/aspnet:10.0
WORKDIR /app
COPY --from=build /app .
ENV ASPNETCORE_URLS=http://0.0.0.0:8000
EXPOSE 8000
ENTRYPOINT ["dotnet", "TimeAgent.Mcp.dll"]
