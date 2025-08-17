#!/bin/bash

# Tgram CLI wrapper script
# Usage: ./tgram.sh [command] [args...]

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if docker-compose is available
if ! command -v docker-compose &> /dev/null; then
    print_error "docker-compose is not installed or not in PATH"
    exit 1
fi

# Check if we're in the right directory
if [ ! -f "docker-compose.yml" ]; then
    print_error "docker-compose.yml not found. Please run this script from the project root directory."
    exit 1
fi

# Function to show help
show_help() {
    echo "Usage: $0 <command> [args...]"
    echo ""
    echo "Commands:"
    echo "  build                    - Build Docker image"
    echo "  logs                     - Show container logs"
    echo "  clean                    - Remove containers and images"
    echo "  shell                    - Start interactive shell in container"
    echo "  help                     - Show this help message"
    echo ""
    echo "Direct main.py commands:"
    echo "  fetch_new                - Fetch newest messages"
    echo "  fetch_old                - Fetch oldest messages"
    echo "  fetch_scan               - Scan for missing messages"
    echo "  fetch_gap <start> <end> - Fetch specific gap"
    echo "  list_chan                - List available channels"
                    echo "  list_native_topics       - List native Telegram topics"
        echo "  fetch_by_native_topic <id> - Fetch messages for native topic"
        echo "  native_topic_stats       - Show native topic statistics"
        echo "  list_virtual_topics      - List virtual topics based on reply chains"
        echo "  fetch_by_virtual_topic <id> - Fetch messages for virtual topic"
        echo "  virtual_topic_stats      - Show virtual topic statistics"
        echo "  hybrid_topic_stats       - Show combined topic statistics"
        echo "  status                   - Show stored message statistics"
    echo ""
    echo "Examples:"
    echo "  $0 fetch_new"
    echo "  $0 fetch_gap 1000 2000"
    echo "  $0 list_virtual_topics"
    echo "  $0 fetch_by_virtual_topic 3"
}

# Function to build the image
build_image() {
    print_info "Building Docker image..."
    docker-compose build
    print_info "Build completed successfully!"
}

# Function to show logs
show_logs() {
    print_info "Showing container logs..."
    docker-compose logs -f
}

# Function to clean up
cleanup() {
    print_warning "This will remove all containers and volumes. Are you sure? (y/N)"
    read -r response
    if [[ "$response" =~ ^([yY][eE][sS]|[yY])$ ]]; then
        print_info "Cleaning up containers and volumes..."
        docker-compose down -v
        docker system prune -f
        print_info "Cleanup completed!"
    else
        print_info "Cleanup cancelled."
    fi
}

# Main script logic
case "${1:-help}" in
    "help"|"-h"|"--help")
        show_help
        ;;
    "build")
        build_image
        ;;
    "logs")
        show_logs
        ;;
    "clean")
        cleanup
        ;;
    "shell")
        print_info "Starting interactive shell in container..."
        docker-compose run --rm --entrypoint="" tgram bash
        ;;
    *)
        # Execute the command in the container
        if [ $# -eq 0 ]; then
            print_info "Starting interactive mode..."
            docker-compose run --rm tgram
        else
            print_info "Executing command: $*"
            docker-compose run --rm tgram "$@"
        fi
        ;;
esac
