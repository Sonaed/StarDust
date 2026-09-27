#include "stardust_core.hpp"

#include <algorithm>
#include <functional>
#include <sstream>
#include <unordered_set>

namespace stardust {
namespace {
std::string quote(const std::string& value) {
    std::string out = "\"";
    for (char c : value) {
        if (c == '\\' || c == '\"') out += '\\';
        if (c == '\n') out += "\\n";
        else out += c;
    }
    return out + "\"";
}
}

Graph::Graph(std::string creator) { reset(creator); }

void Graph::reset(const std::string& creator) {
    creator_ = creator;
    nodes_.clear();
    connections_.clear();
    parameters_.clear();
    if (creator == "blend") {
        parameters_["mode"] = "normal";
        parameters_["channel"] = "RGB";
    } else {
        parameters_["size"] = "10.0";
        parameters_["opacity"] = "1.0";
        parameters_["pressureSize"] = "true";
    }
}

bool Graph::add_node(const std::string& id, const std::string& type) {
    if (id.empty() || type.empty() || std::any_of(nodes_.begin(), nodes_.end(), [&](const Node& n) { return n.id == id; })) return false;
    nodes_.push_back({id, type});
    return true;
}

bool Graph::remove_node(const std::string& id) {
    auto before = nodes_.size();
    nodes_.erase(std::remove_if(nodes_.begin(), nodes_.end(), [&](const Node& n) { return n.id == id; }), nodes_.end());
    connections_.erase(std::remove_if(connections_.begin(), connections_.end(), [&](const Connection& c) { return c.from == id || c.to == id; }), connections_.end());
    return nodes_.size() != before;
}

bool Graph::connect(const std::string& from, const std::string& to) {
    if (from == to) return false;
    auto exists = [&](const std::string& id) { return std::any_of(nodes_.begin(), nodes_.end(), [&](const Node& n) { return n.id == id; }); };
    if (!exists(from) || !exists(to)) return false;
    if (std::any_of(connections_.begin(), connections_.end(), [&](const Connection& c) { return c.from == from && c.to == to; })) return false;
    connections_.push_back({from, to});
    return true;
}

bool Graph::set_parameter(const std::string& key, const std::string& value) {
    if (key.empty()) return false;
    parameters_[key] = value;
    return true;
}

std::vector<std::string> Graph::validate() const {
    std::vector<std::string> errors;
    if (nodes_.empty()) errors.push_back("graph must contain at least one node");
    std::unordered_map<std::string, std::vector<std::string>> adjacency;
    for (const auto& node : nodes_) adjacency[node.id] = {};
    for (const auto& edge : connections_) {
        if (!adjacency.count(edge.from) || !adjacency.count(edge.to)) errors.push_back("connection references an unknown node");
        else adjacency[edge.from].push_back(edge.to);
    }
    std::unordered_set<std::string> visiting, visited;
    std::function<void(const std::string&)> visit = [&](const std::string& id) {
        if (visiting.count(id)) { errors.push_back("graph contains a cycle"); return; }
        if (visited.count(id)) return;
        visiting.insert(id);
        for (const auto& child : adjacency[id]) visit(child);
        visiting.erase(id);
        visited.insert(id);
    };
    for (const auto& node : nodes_) visit(node.id);
    return errors;
}

std::string Graph::serialize() const {
    std::ostringstream out;
    out << "{\"format\":\"StellarDustGraph\",\"version\":1,\"creator\":" << quote(creator_) << ",\"nodes\":[";
    for (size_t i = 0; i < nodes_.size(); ++i) {
        if (i) out << ',';
        out << "{\"id\":" << quote(nodes_[i].id) << ",\"type\":" << quote(nodes_[i].type) << "}";
    }
    out << "],\"connections\":[";
    for (size_t i = 0; i < connections_.size(); ++i) {
        if (i) out << ',';
        out << "{\"from\":" << quote(connections_[i].from) << ",\"to\":" << quote(connections_[i].to) << "}";
    }
    out << "],\"parameters\":{";
    size_t index = 0;
    for (const auto& [key, value] : parameters_) {
        if (index++) out << ',';
        out << quote(key) << ':' << quote(value);
    }
    out << "}}";
    return out.str();
}

std::string Graph::snapshot() const { return serialize(); }
} // namespace stardust
