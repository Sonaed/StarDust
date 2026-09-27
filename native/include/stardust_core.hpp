#pragma once

#include <string>
#include <unordered_map>
#include <vector>

namespace stardust {

struct Node {
    std::string id;
    std::string type;
};

struct Connection {
    std::string from;
    std::string to;
};

class Graph {
public:
    explicit Graph(std::string creator = "brush_engine");

    void reset(const std::string& creator);
    bool add_node(const std::string& id, const std::string& type);
    bool remove_node(const std::string& id);
    bool connect(const std::string& from, const std::string& to);
    bool set_parameter(const std::string& key, const std::string& value);

    std::vector<std::string> validate() const;
    std::string serialize() const;
    std::string snapshot() const;
    const std::unordered_map<std::string, std::string>& parameters() const { return parameters_; }

private:
    std::string creator_;
    std::vector<Node> nodes_;
    std::vector<Connection> connections_;
    std::unordered_map<std::string, std::string> parameters_;
};

} // namespace stardust
